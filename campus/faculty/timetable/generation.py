"""M07-03 Timetable generation as a background job.

`start_generation` queues a Timetable Generation Run; `execute_run` (the job) builds the problem from the term's
submitted Course Allocations, solves it and replaces the Timetable's grid with the result. Classes the solver did not
place are recorded on the run, never hidden. At most one live run exists per Timetable; a run that outlived the job
timeout counts as dead, and a live run can be cancelled.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime

from campus.faculty.timetable import context, solver

QUEUE = "long"
JOB_TIMEOUT = 3600
STALE_MARGIN = 600  # seconds past the job timeout before a live-looking run is written off
MAX_TIME_LIMIT = 300  # seconds a solve may be given
SAVEPOINT = "timetable_generation"
LIVE = ("Queued", "Running")
CANCEL_ROLES = ("System Manager", "Dean Academics", "Academics User", "HOD")


@frappe.whitelist()
def start_generation(timetable, time_limit=None, replace_existing=0):
	"""Queue a run for `timetable`; returns the Timetable Generation Run name. A filled grid is replaced only with `replace_existing`."""
	doc = frappe.get_doc("Timetable", timetable)
	doc.check_permission("write")
	if doc.entries and not cint(replace_existing):
		frappe.throw(_("{0} already has a grid; generating replaces it, manual edits included. Confirm to replace it.").format(timetable))
	frappe.db.get_value("Timetable", timetable, "name", for_update=True)  # serialises concurrent starts
	expire_dead_runs(timetable)
	if live_runs(timetable):
		frappe.throw(_("{0} already has a generation run in progress.").format(timetable))
	limit = min(max(cint(time_limit) or solver.DEFAULT_TIME_LIMIT, 1), MAX_TIME_LIMIT)
	run = frappe.get_doc({"doctype": "Timetable Generation Run", "timetable": timetable, "status": "Queued", "time_limit": limit}).insert(
		ignore_permissions=True
	)
	frappe.enqueue(
		"campus.faculty.timetable.generation.execute_run", queue=QUEUE, timeout=JOB_TIMEOUT, now=frappe.in_test, enqueue_after_commit=True, run=run.name
	)
	return run.name


@frappe.whitelist()
def cancel_run(run):
	"""Cancel a queued or running run; a running solve finishes but its result is discarded."""
	frappe.only_for(CANCEL_ROLES)
	status = frappe.db.get_value("Timetable Generation Run", run, "status", for_update=True)
	if status not in LIVE:
		frappe.throw(_("Run {0} is {1}; only a queued or running run can be cancelled.").format(run, _(status)))
	frappe.db.set_value("Timetable Generation Run", run, {"status": "Cancelled", "finished_at": now_datetime()})


def live_runs(timetable):
	"""Queued or running runs of the timetable, read with a lock (after the Timetable row lock) so a concurrent start sees them."""
	run = frappe.qb.DocType("Timetable Generation Run")
	return frappe.qb.from_(run).select(run.name).where((run.timetable == timetable) & run.status.isin(LIVE)).for_update().run()


def expire_dead_runs(timetable):
	"""A queued or running run untouched for longer than the job timeout plus a margin lost its worker: mark it Failed."""
	cutoff = add_to_date(now_datetime(), seconds=-(JOB_TIMEOUT + STALE_MARGIN))
	dead = frappe.get_all("Timetable Generation Run", {"timetable": timetable, "status": ["in", LIVE], "modified": ["<", cutoff]}, pluck="name")
	for name in dead:
		frappe.db.set_value(
			"Timetable Generation Run", name,
			{"status": "Failed", "error": _("The run did not finish: its worker was lost or timed out."), "finished_at": now_datetime()},
			update_modified=False,
		)  # fmt: skip


def execute_run(run):
	"""The job: solve and store. A failure is recorded on the run (message only: the frames hold no secrets, but none are needed)."""
	if frappe.db.get_value("Timetable Generation Run", run, "status", for_update=True) != "Queued":
		return
	frappe.db.set_value("Timetable Generation Run", run, {"status": "Running", "started_at": now_datetime()}, update_modified=False)
	commit()
	doc = frappe.get_doc("Timetable Generation Run", run)
	frappe.db.savepoint(SAVEPOINT)
	try:
		outcome = generate(doc)
	except Exception as error:
		frappe.db.rollback(save_point=SAVEPOINT)  # undo the half-written grid, keep the run row
		doc.db_set({"status": "Failed", "error": str(error)[:1000], "finished_at": now_datetime()}, update_modified=False)
	else:
		if outcome:
			doc.db_set({**outcome, "finished_at": now_datetime()}, update_modified=False)
	commit()


def commit():
	if not frappe.in_test:
		frappe.db.commit()  # nosemgrep: the worker publishes progress between steps; tests run in one rolled-back transaction


def cancelled(run):
	return frappe.db.get_value("Timetable Generation Run", run.name, "status", for_update=True) == "Cancelled"


def generate(run):
	"""Solve and write the grid; None when the run was cancelled (before or during the solve)."""
	if cancelled(run):
		return None
	timetable = frappe.get_doc("Timetable", run.timetable, for_update=True)
	problem, template = context.build_problem(timetable, run.time_limit)
	result = solver.solve(problem)
	if cancelled(run):
		return None
	timetable.set("entries", context.as_rows(result.entries, template))
	timetable.flags.from_generation = True
	timetable.save(ignore_permissions=True)
	return {
		"status": "Completed" if not result.unmet else "Completed with unmet constraints",
		"sessions_total": len(problem.sessions), "sessions_placed": len(problem.sessions) - result.unplaced,
		"soft_issues": result.soft_issues, "solver_status": f"{result.backend} {result.status}", "unmet": "\n".join(result.unmet) or None,
	}  # fmt: skip
