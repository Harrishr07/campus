"""NFR-PERF Bulk job runner (P1-T09): resumable, idempotent background runs over many items.

Usage: `run_bulk("Hall Tickets", items, "app.module.handler", key="app.module.key_of")`.

Design
- Items are JSON on the Bulk Run (`items`, Long Text): 5,000 student-sized items are a few hundred KB, far
  under the LONGTEXT/max_allowed_packet limits; a File would add a second store to keep consistent for no gain
  at campus scale. Revisit (File-backed items) only if a run needs ~100k+ items.
- Progress is persisted per chunk: processed keys go in `processed_keys` (Bulk Run Item Key rows), failures in
  `errors`, counters on the run. Handler side effects, keys, errors and counters share one transaction that is
  committed once per chunk, so a killed worker loses at most the chunk in flight (rolled back with it) and a
  resume skips exactly the keys that were committed: every item is processed once.
- A failing item is rolled back to a savepoint, logged and skipped; failed items are not retried on resume.
- Each chunk locks the run row and re-checks its keys against those already committed, so two workers on one
  run never process an item twice. The handler runs as the user who created the run.

Handler contract (exactly-once holds only within it)
- The handler must be DB-only and must NOT commit or roll back the transaction: a commit makes the chunk
  non-atomic, so the runner aborts the run as Failed with a clear error.
- Non-transactional side effects (email, API calls, files) cannot be rolled back with the chunk, so a crash
  can repeat them for the in-flight chunk: delivery is at-least-once unless the handler makes them idempotent
  using the item key.
"""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.background_jobs import get_job, get_redis_conn
from rq.job import JobStatus

QUEUE = "long"
TIMEOUT = 4 * 60 * 60
KEY_LENGTH = 140
RESUMABLE = ("Queued", "Running", "Failed")
FINISHED = ("Completed", "Completed with errors")
SAVEPOINT = "bulk_item"


def run_bulk(run_type, items, handler, chunk=200, key=None, parameters=None):
	"""Create a Bulk Run for `handler(item, run)` over `items` and queue it; returns the Bulk Run name.

	`handler` and `key` are dotted paths (they must survive being enqueued). `key(item) -> str` is the
	idempotency key (default `str(item)`); items with an already seen key are dropped. Items and
	`parameters` must be JSON-serialisable.

	Contract: `handler` must be DB-only and must not commit (the runner commits per chunk, and fails the run
	if a handler commits). Anything non-transactional (email, API, files) is at-least-once; make it idempotent
	with the item key. The handler runs as the user who calls `run_bulk`.
	"""
	_resolve(handler)
	key_fn = _resolve(key) if key else str
	unique = _unique_items(items, key_fn)
	run = frappe.get_doc(
		{
			"doctype": "Bulk Run",
			"run_type": run_type,
			"status": "Queued",
			"handler": handler,
			"key_function": key,
			"chunk_size": max(int(chunk), 1),
			"parameters": _to_json(parameters) if parameters is not None else None,
			"items": _to_json(unique),
			"total": len(unique),
		}
	)
	run.insert(ignore_permissions=True)
	enqueue_run(run.name)
	return run.name


@frappe.whitelist()
def resume_bulk(name):
	"""Re-queue a Queued, Failed or crashed Running run; it continues after the last committed chunk.

	A Running run whose job is still alive is left alone. The handler still runs as the run's creator.
	"""
	frappe.only_for("System Manager")
	status = frappe.db.get_value("Bulk Run", name, "status", for_update=True)
	if status not in RESUMABLE:
		frappe.throw(_("Bulk Run {0} is {1} and cannot be resumed.").format(name, status))
	if status == "Running" and _job_alive(name):
		return
	_clear_dead_job(name)
	if status == "Failed":
		frappe.db.set_value("Bulk Run", name, "status", "Queued")
	enqueue_run(name)


def _job_id(name):
	return f"bulk-run::{name}"


def _job_alive(name):
	"""True if the run's RQ job is queued, or started by a worker that is still registered."""
	job = get_job(_job_id(name))
	if not job:
		return False
	status = job.get_status(refresh=False)
	if status == JobStatus.QUEUED:
		return True
	return status == JobStatus.STARTED and bool(
		job.worker_name and get_redis_conn().exists(f"rq:worker:{job.worker_name}")
	)


def _clear_dead_job(name):
	"""Delete the run's leftover RQ job (e.g. STARTED by a killed worker) so enqueue's dedupe cannot swallow the resume."""
	job = get_job(_job_id(name))
	if job and not _job_alive(name):
		job.delete()


def enqueue_run(name):
	"""Queue the worker for run `name` once; a run already queued or running is not queued again."""
	frappe.enqueue(
		"campus.campus_platform.bulk.process_bulk_run",
		queue=QUEUE,
		timeout=TIMEOUT,
		job_id=_job_id(name),
		deduplicate=True,
		enqueue_after_commit=True,
		name=name,
	)


def process_bulk_run(name):
	"""Worker entry point: process the run's unprocessed items in chunks, committing after each chunk."""
	run = frappe.get_doc("Bulk Run", name)
	if run.status in FINISHED:
		return
	caller = frappe.session.user
	frappe.set_user(run.owner)
	try:
		_run_as_owner(run)
	finally:
		frappe.set_user(caller)


def _run_as_owner(run):
	run.db_set({"status": "Running", "started_at": run.started_at or now_datetime()}, update_modified=False)
	frappe.db.commit()
	try:
		_process_chunks(run)
	except Exception:
		frappe.db.rollback()
		run.db_set({"status": "Failed", "finished_at": now_datetime()}, update_modified=False)
		frappe.db.commit()
		raise
	_finish(run)


def _process_chunks(run):
	handler = frappe.get_attr(run.handler)
	key_fn = frappe.get_attr(run.key_function) if run.key_function else str
	seen = set(frappe.get_all("Bulk Run Item Key", filters={"parent": run.name}, pluck="item_key", limit=0))
	pending = [item for item in json.loads(run.items) if _key(key_fn, item) not in seen]
	# The key read above is a plain (snapshot) read; end its transaction so the first chunk's first
	# consistent read is the handler's own, like every later chunk (each starts after a commit).
	frappe.db.commit()
	for start in range(0, len(pending), run.chunk_size):
		_process_chunk(run, handler, key_fn, pending[start : start + run.chunk_size])


def _process_chunk(run, handler, key_fn, chunk):
	"""Process one chunk under a lock on the run row; the lock is released by the chunk's commit."""
	frappe.db.get_value("Bulk Run", run.name, "name", for_update=True)
	# Locking reads (for_update) see the latest committed rows; plain reads would use the REPEATABLE READ
	# snapshot, which may predate another worker's commit (e.g. the key read done before the first chunk).
	run.done, run.failed = frappe.db.get_value("Bulk Run", run.name, ["done", "failed"], for_update=True)
	chunk = _not_yet_processed(run.name, key_fn, chunk)
	keys, errors = [], []
	for item in chunk:
		item_key = _key(key_fn, item)
		keys.append(item_key)
		error = _run_item(handler, item, run)
		if error:
			errors.append((item_key, *error))
	run.done += len(keys) - len(errors)
	run.failed += len(errors)
	_insert_children(run.name, "processed_keys", "Bulk Run Item Key", [(k,) for k in keys], ("item_key",))
	_insert_children(
		run.name, "errors", "Bulk Run Row Error", errors, ("item_key", "error", "traceback"), run.failed - len(errors)
	)
	frappe.db.set_value("Bulk Run", run.name, {"done": run.done, "failed": run.failed}, update_modified=False)
	frappe.db.commit()
	_publish_progress(run, "Running")


def _not_yet_processed(name, key_fn, chunk):
	"""Drop items another worker has committed since this worker read the run's keys."""
	keys = [_key(key_fn, item) for item in chunk]
	table = frappe.qb.DocType("Bulk Run Item Key")
	rows = (
		frappe.qb.from_(table)
		.select(table.item_key)
		.where((table.parent == name) & table.item_key.isin(keys))
		.for_update()
		.run()
	)
	committed = {row[0] for row in rows}
	return [item for item, item_key in zip(chunk, keys) if item_key not in committed]


def _run_item(handler, item, run):
	"""Run the handler for one item; returns None on success, else (message, traceback) after undoing its writes."""
	committed = []
	frappe.db.after_commit.add(lambda: committed.append(True))
	frappe.db.savepoint(SAVEPOINT)
	try:
		handler(item, run)
	except Exception as e:
		if committed:
			_raise_handler_committed(item, e)
		frappe.db.rollback(save_point=SAVEPOINT)
		return str(e)[:1000], frappe.get_traceback(with_context=False)
	if committed:
		_raise_handler_committed(item)
	frappe.db.release_savepoint(SAVEPOINT)


def _raise_handler_committed(item, cause=None):
	message = _("Bulk Run handler committed the transaction while processing {0}; handlers must not commit.")
	raise frappe.ValidationError(message.format(frappe.as_json(item)[:80])) from cause


def _finish(run):
	status = "Completed with errors" if run.failed else "Completed"
	run.db_set({"status": status, "finished_at": now_datetime()}, update_modified=False)
	frappe.db.commit()
	_publish_progress(run, status)


def _publish_progress(run, status):
	processed = run.done + run.failed
	frappe.publish_realtime(
		"bulk_run_progress",
		{
			"name": run.name,
			"status": status,
			"total": run.total,
			"done": run.done,
			"failed": run.failed,
			"percent": round(processed * 100 / run.total) if run.total else 100,
		},
		doctype="Bulk Run",
		docname=run.name,
	)


def _insert_children(parent, parentfield, doctype, rows, fields, first_idx=0):
	"""Insert child rows directly: loading and saving the parent per chunk would be quadratic."""
	if not rows:
		return
	if parentfield == "processed_keys":
		first_idx = frappe.db.count(doctype, {"parent": parent})
	now = now_datetime()
	user = frappe.session.user
	base = ("name", "parent", "parenttype", "parentfield", "idx", "creation", "modified", "owner", "modified_by")
	values = [
		(frappe.generate_hash(length=10), parent, "Bulk Run", parentfield, first_idx + i + 1, now, now, user, user, *row)
		for i, row in enumerate(rows)
	]
	frappe.db.bulk_insert(doctype, [*base, *fields], values)


def _resolve(dotted_path):
	try:
		return frappe.get_attr(dotted_path)
	except (AttributeError, ImportError):
		frappe.throw(_("Bulk Run cannot resolve {0}.").format(dotted_path))


def _unique_items(items, key_fn):
	seen, unique = set(), []
	for item in items:
		item_key = _key(key_fn, item)
		if item_key not in seen:
			seen.add(item_key)
			unique.append(item)
	return unique


def _key(key_fn, item):
	item_key = str(key_fn(item))
	if len(item_key) > KEY_LENGTH:
		frappe.throw(_("Bulk Run item key is longer than {0} characters: {1}").format(KEY_LENGTH, item_key[:40]))
	return item_key


def _to_json(value):
	try:
		return json.dumps(value)
	except TypeError:
		frappe.throw(_("Bulk Run items and parameters must be JSON-serialisable."))
