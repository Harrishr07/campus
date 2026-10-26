"""P1-T09 bulk job runner: resume after crash, idempotency, error capture, progress, 5,000 items."""

import time
from unittest.mock import MagicMock, patch

import frappe
from rq.job import JobStatus

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

	def test_resume_leaves_a_live_running_run_alone(self):
		name = self.start([1, 2, 3])
		frappe.db.set_value("Bulk Run", name, "status", "Running")
		self.enqueue.reset_mock()
		with patch.object(bulk, "_job_alive", return_value=True):
			bulk.resume_bulk(name)
		self.enqueue.assert_not_called()
		self.assertEqual(frappe.db.get_value("Bulk Run", name, "status"), "Running")

	def test_resume_of_crashed_running_run_keeps_status_and_clears_dead_job(self):
		name = self.start([1, 2, 3])
		frappe.db.set_value("Bulk Run", name, "status", "Running")
		job = MagicMock()
		with (
			patch.object(bulk, "get_job", return_value=job),
			patch.object(bulk, "_job_alive", return_value=False),
		):
			bulk.resume_bulk(name)
		job.delete.assert_called_once()
		self.assertEqual(frappe.db.get_value("Bulk Run", name, "status"), "Running")
		self.assertEqual(self.enqueue.call_count, 2)

	def _started_job(self, worker_name):
		job = MagicMock()
		job.get_status.return_value = JobStatus.STARTED
		job.worker_name = worker_name
		return job

	def test_job_alive_checks_worker_registration_in_redis(self):
		redis = MagicMock()
		redis.exists.return_value = 1
		with (
			patch.object(bulk, "get_job", return_value=self._started_job("w1")),
			patch.object(bulk, "get_redis_conn", return_value=redis),
		):
			self.assertTrue(bulk._job_alive("BULK-1"))
			redis.exists.assert_called_once_with("rq:worker:w1")
			redis.exists.return_value = 0
			self.assertFalse(bulk._job_alive("BULK-1"))

	def test_job_alive_for_queued_missing_and_workerless_jobs(self):
		queued = MagicMock()
		queued.get_status.return_value = JobStatus.QUEUED
		with patch.object(bulk, "get_job", return_value=queued):
			self.assertTrue(bulk._job_alive("BULK-1"))
		with patch.object(bulk, "get_job", return_value=None):
			self.assertFalse(bulk._job_alive("BULK-1"))
		with patch.object(bulk, "get_job", return_value=self._started_job(None)):
			self.assertFalse(bulk._job_alive("BULK-1"))

	def test_resume_running_run_with_started_job_of_live_worker_is_noop(self):
		name = self.start([1])
		frappe.db.set_value("Bulk Run", name, "status", "Running")
		self.enqueue.reset_mock()
		redis = MagicMock()
		redis.exists.return_value = 1
		with (
			patch.object(bulk, "get_job", return_value=self._started_job("w1")),
			patch.object(bulk, "get_redis_conn", return_value=redis),
		):
			bulk.resume_bulk(name)
		self.enqueue.assert_not_called()

	def test_resume_running_run_with_started_job_of_dead_worker_replaces_job(self):
		name = self.start([1])
		frappe.db.set_value("Bulk Run", name, "status", "Running")
		job = self._started_job("gone")
		redis = MagicMock()
		redis.exists.return_value = 0
		with (
			patch.object(bulk, "get_job", return_value=job),
			patch.object(bulk, "get_redis_conn", return_value=redis),
		):
			bulk.resume_bulk(name)
		job.delete.assert_called_once()
		self.assertEqual(self.enqueue.call_count, 2)

	def test_second_worker_with_stale_chunk_cannot_double_process(self):
		name = self.start(list(range(10)), chunk=10)
		run = frappe.get_doc("Bulk Run", name)
		chunk = list(range(10))
		bulk._process_chunk(run, h.record, str, chunk)  # worker A commits the chunk
		stale = frappe.get_doc("Bulk Run", name)
		stale.done = stale.failed = 0  # worker B read the run before A committed
		bulk._process_chunk(stale, h.record, str, chunk)
		self.assertEqual(h.todo_count(), 10)
		run.reload()
		self.assertEqual((run.done, run.failed, len(run.processed_keys)), (10, 0, 10))

	def test_process_twice_does_not_duplicate(self):
		name = self.start(list(range(30)), chunk=10)
		bulk.process_bulk_run(name)
		frappe.db.set_value("Bulk Run", name, {"status": "Running", "finished_at": None})
		bulk.process_bulk_run(name)
		self.assertEqual(h.todo_count(), 30)
		self.assertEqual(frappe.db.get_value("Bulk Run", name, "done"), 30)

	def test_handler_that_commits_fails_the_run_clearly(self):
		name = self.start([1, 2], handler="commit_in_handler")
		with self.assertRaises(frappe.ValidationError) as ctx:
			bulk.process_bulk_run(name)
		self.assertIn("must not commit", str(ctx.exception))
		self.assertEqual(frappe.db.get_value("Bulk Run", name, "status"), "Failed")

	def test_handler_that_commits_then_raises_fails_the_run_not_the_savepoint(self):
		name = self.start([1], handler="commit_then_fail")
		with self.assertRaises(frappe.ValidationError) as ctx:
			bulk.process_bulk_run(name)
		self.assertIn("must not commit", str(ctx.exception))
		self.assertEqual(frappe.db.get_value("Bulk Run", name, "status"), "Failed")

	def test_non_item_failure_marks_run_failed_and_reraises(self):
		name = self.start([1, 2, 3])
		with patch.object(bulk, "_insert_children", side_effect=RuntimeError("db down")):
			with self.assertRaises(RuntimeError):
				bulk.process_bulk_run(name)
		run = frappe.get_doc("Bulk Run", name)
		self.assertEqual(run.status, "Failed")
		self.assertTrue(run.finished_at)
		self.assertEqual(run.done, 0)
		bulk.resume_bulk(name)  # Failed runs are resumable
		bulk.process_bulk_run(name)
		self.assertEqual(frappe.db.get_value("Bulk Run", name, "status"), "Completed")
		self.assertEqual(h.todo_count(), 3)

	def test_handler_runs_as_run_owner_not_resumer(self):
		frappe.set_user("test@example.com")
		try:
			name = self.start([1], handler="record_session_user")
		finally:
			frappe.set_user("Administrator")
		bulk.resume_bulk(name)
		bulk.process_bulk_run(name)
		self.assertEqual(h.todo_count("1@test@example.com"), 1)
		self.assertEqual(frappe.session.user, "Administrator")

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
