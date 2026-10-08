"""M07-03 Timetable generation as a background job.

`start_generation` queues a Timetable Generation Run; `execute_run` (the job) builds the problem from the term's
submitted Course Allocations, solves it and replaces the Timetable's grid with the result. Constraints the solver
could not satisfy are recorded on the run, never hidden. At most one live run exists per Timetable.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from campus.faculty.timetable import context, solver

QUEUE = "long"
SAVEPOINT = "timetable_generation"
LIVE = ("Queued", "Running")


@frappe.whitelist()
def start_generation(timetable, time_limit=None):
	"""Queue a run for `timetable`; returns the Timetable Generation Run name."""
	doc = frappe.get_doc("Timetable", timetable)
	doc.check_permission("write")
	frappe.db.get_value("Timetable", timetable, "name", for_update=True)  # serialises concurrent starts
	if live_runs(timetable):
		frappe.throw(_("{0} already has a generation run in progress.").format(timetable))
	run = frappe.get_doc(
		{"doctype": "Timetable Generation Run", "timetable": timetable, "status": "Queued", "time_limit": time_limit or solver.DEFAULT_TIME_LIMIT}
	).insert(ignore_permissions=True)
	frappe.enqueue(
		"campus.faculty.timetable.generation.execute_run", queue=QUEUE, timeout=3600, now=frappe.in_test, enqueue_after_commit=True, run=run.name
	)
	return run.name


def live_runs(timetable):
	"""Queued or running runs of the timetable, read with a lock (after the Timetable row lock) so a concurrent start sees them."""
	run = frappe.qb.DocType("Timetable Generation Run")
	return frappe.qb.from_(run).select(run.name).where((run.timetable == timetable) & run.status.isin(LIVE)).for_update().run()


def execute_run(run):
	"""The job: solve and store. A failure is recorded on the run (message only: the frames hold no secrets, but none are needed)."""
	doc = frappe.get_doc("Timetable Generation Run", run)
	if doc.status != "Queued":
		return
	doc.db_set({"status": "Running", "started_at": now_datetime()}, update_modified=False)
	commit()
	frappe.db.savepoint(SAVEPOINT)
	try:
		outcome = generate(doc)
	except Exception as error:
		frappe.db.rollback(save_point=SAVEPOINT)  # undo the half-written grid, keep the run row
		doc.db_set({"status": "Failed", "error": str(error)[:1000], "finished_at": now_datetime()}, update_modified=False)
	else:
		doc.db_set({**outcome, "finished_at": now_datetime()}, update_modified=False)
	commit()


def commit():
	if not frappe.in_test:
		frappe.db.commit()  # nosemgrep: the worker publishes progress between steps; tests run in one rolled-back transaction


def generate(run):
	timetable = frappe.get_doc("Timetable", run.timetable, for_update=True)
	problem, template = context.build_problem(timetable, run.time_limit)
	result = solver.solve(problem)
	timetable.set("entries", context.as_rows(result.entries, template))
	timetable.flags.from_generation = True
	timetable.save(ignore_permissions=True)
	return {
		"status": "Completed" if not result.unmet else "Completed with unmet constraints",
		"sessions_total": len(problem.sessions), "sessions_placed": len(problem.sessions) - len(result.unmet), "soft_issues": result.soft_issues,
		"unmet": "\n".join(result.unmet) or None,
	}  # fmt: skip
