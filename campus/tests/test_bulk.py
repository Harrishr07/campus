"""P1-T09 bulk job runner: resume after crash, idempotency, error capture, progress, 5,000 items."""

import time
from unittest.mock import patch

import frappe

from campus.campus_platform import bulk
from campus.tests import bulk_handlers as h
from campus.tests.utils import CampusTestCase

H = "campus.tests.bulk_handlers."
REAL_ENQUEUE_RUN = bulk.enqueue_run


class TestBulkRun(CampusTestCase):
	def setUp(self):
		h.state.update(crash_after=None, calls=0)
		h.cleanup()
		self.addCleanup(h.cleanup)
		patcher = patch.object(bulk, "enqueue_run")
		self.enqueue = patcher.start()
		self.addCleanup(patcher.stop)

	def start(self, items, handler="record", **kwargs):
		name = bulk.run_bulk("test-run", items, H + handler, **kwargs)
		frappe.db.commit()
		return name

	def test_run_completes_and_counts(self):
		name = self.start(list(range(450)), chunk=200)
		self.enqueue.assert_called_once_with(name)
		bulk.process_bulk_run(name)
		run = frappe.get_doc("Bulk Run", name)
		self.assertEqual((run.status, run.total, run.done, run.failed), ("Completed", 450, 450, 0))
		self.assertTrue(run.started_at and run.finished_at)
		self.assertEqual(h.todo_count(), 450)

	def test_enqueue_uses_long_queue_and_run_job_id(self):
		with patch.object(bulk.frappe, "enqueue") as enqueue:
			REAL_ENQUEUE_RUN("BULK-X")
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(kwargs["queue"], "long")
		self.assertEqual(kwargs["job_id"], "bulk-run::BULK-X")
		self.assertTrue(kwargs["deduplicate"])
		self.assertTrue(kwargs["enqueue_after_commit"])
		self.assertEqual(kwargs["name"], "BULK-X")

	def test_resume_after_simulated_crash_processes_each_item_exactly_once(self):
		name = self.start(list(range(1000)), handler="record_or_crash", chunk=200)
		h.state["crash_after"] = 450  # dies in the middle of the third chunk
		with self.assertRaises(h.SimulatedCrash):
			bulk.process_bulk_run(name)
		frappe.db.rollback()  # what the database does when the worker process is killed
		run = frappe.get_doc("Bulk Run", name)
		self.assertEqual((run.status, run.done), ("Running", 400))
		self.assertEqual(h.todo_count(), 400)

		h.state["crash_after"] = None
		bulk.resume_bulk(name)
		self.assertEqual(self.enqueue.call_count, 2)
		bulk.process_bulk_run(name)

		run.reload()
		self.assertEqual((run.status, run.done, run.failed), ("Completed", 1000, 0))
		keys = frappe.get_all("ToDo", filters={"description": ["like", f"{h.MARK}%"]}, pluck="description")
		self.assertEqual(len(keys), 1000)
		self.assertEqual(len(set(keys)), 1000)

	def test_resume_rejects_finished_run(self):
		name = self.start([1], chunk=10)
		bulk.process_bulk_run(name)
		with self.assertRaises(frappe.ValidationError):
			bulk.resume_bulk(name)

	def test_failed_run_can_be_resumed(self):
		name = self.start([1, 2, 3])
		frappe.db.set_value("Bulk Run", name, "status", "Failed")
		bulk.resume_bulk(name)
		self.assertEqual(frappe.db.get_value("Bulk Run", name, "status"), "Queued")

	def test_reprocessing_a_finished_run_does_nothing(self):
		name = self.start(list(range(10)))
		bulk.process_bulk_run(name)
		bulk.process_bulk_run(name)
		self.assertEqual(h.todo_count(), 10)

	def test_duplicate_items_are_processed_once(self):
		name = self.start([1, 2, 2, 3, 1])
		run = frappe.get_doc("Bulk Run", name)
		self.assertEqual(run.total, 3)
		bulk.process_bulk_run(name)
		self.assertEqual(h.todo_count(), 3)

	def test_custom_key_function_and_dict_items(self):
		items = [{"id": 1, "x": "a"}, {"id": 1, "x": "b"}, {"id": 2, "x": "c"}]
		name = self.start(items, handler="record_dict", key=H + "key_by_id")
		bulk.process_bulk_run(name)
		run = frappe.get_doc("Bulk Run", name)
		self.assertEqual((run.total, run.done), (2, 2))
		self.assertEqual(sorted(k.item_key for k in run.processed_keys), ["id-1", "id-2"])

	def test_item_errors_are_logged_and_rolled_back_run_continues(self):
		name = self.start(list(range(10)), handler="record_unless_odd", chunk=4)
		bulk.process_bulk_run(name)
		run = frappe.get_doc("Bulk Run", name)
		self.assertEqual((run.status, run.done, run.failed), ("Completed with errors", 5, 5))
		self.assertEqual(sorted(e.item_key for e in run.errors), ["1", "3", "5", "7", "9"])
		self.assertIn("odd item 3", [e for e in run.errors if e.item_key == "3"][0].error)
		self.assertIn("Traceback", [e for e in run.errors if e.item_key == "3"][0].traceback)
		self.assertEqual(h.todo_count(), 5)  # failed items' partial writes rolled back

	def test_failed_items_are_not_retried_on_resume(self):
		name = self.start([1, 2, 3], handler="record_unless_odd")
		bulk.process_bulk_run(name)
		frappe.db.set_value("Bulk Run", name, "status", "Running")
		bulk.process_bulk_run(name)
		run = frappe.get_doc("Bulk Run", name)
		self.assertEqual((run.done, run.failed, len(run.errors)), (1, 2, 2))

	def test_parameters_reach_handler(self):
		name = self.start([1, 2], handler="record_with_parameter", parameters={"prefix": "p"})
		bulk.process_bulk_run(name)
		self.assertEqual(h.todo_count("p-"), 2)

	def test_progress_published_after_each_chunk(self):
		name = self.start(list(range(450)), chunk=200)
		with patch.object(bulk.frappe, "publish_realtime") as publish:
			bulk.process_bulk_run(name)
		progress = [c for c in publish.call_args_list if c.args and c.args[0] == "bulk_run_progress"]
		self.assertEqual(len(progress), 4)  # three chunks plus the final status
		first = progress[0]
		self.assertEqual(first.args[0], "bulk_run_progress")
		self.assertEqual((first.kwargs["doctype"], first.kwargs["docname"]), ("Bulk Run", name))
		self.assertEqual(first.args[1]["done"], 200)
		self.assertEqual(progress[-1].args[1]["status"], "Completed")

	def test_unresolvable_handler_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			bulk.run_bulk("test-run", [1], "campus.tests.bulk_handlers.nope")

	def test_non_serialisable_items_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			bulk.run_bulk("test-run", [object()], H + "record")

	def test_empty_run_completes(self):
		name = self.start([])
		bulk.process_bulk_run(name)
		self.assertEqual(frappe.db.get_value("Bulk Run", name, "status"), "Completed")

	def test_5000_item_run_completes(self):
		started = time.monotonic()
		name = self.start(list(range(5000)), chunk=200)
		bulk.process_bulk_run(name)
		elapsed = time.monotonic() - started
		print(f"\n5,000-item bulk run: {elapsed:.1f}s")
		run = frappe.get_doc("Bulk Run", name)
		self.assertEqual((run.status, run.done, run.failed), ("Completed", 5000, 0))
		self.assertEqual(h.todo_count(), 5000)
