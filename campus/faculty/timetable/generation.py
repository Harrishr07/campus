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
CANCEL_ROLES = ("System Manager", "Dean Academics", "Academics User")  # and write permission on the Timetable


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
	"""Cancel a queued or running run. Compare-and-set, so it never waits for the worker: the solve finishes, the worker
	sees the run is no longer Running and discards its result."""
	frappe.only_for(CANCEL_ROLES)
	timetable = frappe.db.get_value("Timetable Generation Run", run, "timetable")
	if not timetable:
		frappe.throw(_("Run {0} does not exist.").format(run))
	frappe.get_doc("Timetable", timetable).check_permission("write")
	frappe.db.sql(
		"update `tabTimetable Generation Run` set status = 'Cancelled', finished_at = %s where name = %s and status in ('Queued', 'Running')",
		(now_datetime(), run),
	)
	if not frappe.db.sql("select row_count()")[0][0]:
		frappe.throw(_("Run {0} is {1}; only a queued or running run can be cancelled.").format(run, _(frappe.db.get_value("Timetable Generation Run", run, "status"))))


def live_runs(timetable):
	"""Queued or running runs of the timetable, read with a lock (after the Timetable row lock) so a concurrent start sees them."""
	run = frappe.qb.DocType("Timetable Generation Run")
	return frappe.qb.from_(run).select(run.name).where((run.timetable == timetable) & run.status.isin(LIVE)).for_update().run()


def expire_dead_runs(timetable):
	"""A queued or running run that began (or, if never started, was created) longer ago than the job timeout plus a margin
	lost its worker: mark it Failed."""
	cutoff = add_to_date(now_datetime(), seconds=-(JOB_TIMEOUT + STALE_MARGIN))
	for run in frappe.get_all("Timetable Generation Run", {"timetable": timetable, "status": ["in", LIVE]}, ["name", "started_at", "creation"]):
		if (run.started_at or run.creation) < cutoff:
			frappe.db.set_value(
				"Timetable Generation Run", run.name,
				{"status": "Failed", "error": _("The run did not finish: its worker was lost or timed out."), "finished_at": now_datetime()},
				update_modified=False,
			)  # fmt: skip


def execute_run(run):
	"""The job: solve and store. Failures are recorded on the run (message only); a run cancelled meanwhile stays cancelled."""
	if frappe.db.get_value("Timetable Generation Run", run, "status", for_update=True) != "Queued":
		return
	frappe.db.set_value("Timetable Generation Run", run, {"status": "Running", "started_at": now_datetime()}, update_modified=False)
	commit()  # releases the lock: cancel_run and other readers are never blocked by the solve
	doc = frappe.get_doc("Timetable Generation Run", run)
	try:
		outcome = generate(doc)
	except Exception as error:
		finish(run, {"status": "Failed", "error": str(error)[:1000]})
	else:
		if outcome:
			finish(run, outcome)
	commit()


def finish(run, values):
	"""Record the outcome only while the run is still Running (a cancel in between wins)."""
	if frappe.db.get_value("Timetable Generation Run", run, "status", for_update=True) == "Running":
		frappe.db.set_value("Timetable Generation Run", run, {**values, "finished_at": now_datetime()}, update_modified=False)


def commit():
	if not frappe.in_test:
		frappe.db.commit()  # nosemgrep: the worker publishes progress between steps; tests run in one rolled-back transaction


def write_grid(timetable, rows):
	"""Replace the grid under the Timetable lock; a failed save is undone and leaves the run row alone."""
	timetable = frappe.get_doc("Timetable", timetable, for_update=True)
	frappe.db.savepoint(SAVEPOINT)
	try:
		timetable.set("entries", rows)
		timetable.flags.from_generation = True
		timetable.save(ignore_permissions=True)
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise


def still_running(run):
	"""Latest committed status, read with a lock held only until the write that follows commits."""
	return frappe.db.get_value("Timetable Generation Run", run.name, "status", for_update=True) == "Running"


def generate(run):
	"""Solve (holding no locks), then write the grid under short locks; None when the run was cancelled meanwhile."""
	timetable = frappe.get_doc("Timetable", run.timetable)
	problem, template = context.build_problem(timetable, run.time_limit)
	commit()  # end the read transaction: the solve holds no snapshot and no locks
	result = solver.solve(problem)
	if not still_running(run):
		return None
	write_grid(run.timetable, context.as_rows(result.entries, template))
	return {
		"status": "Completed" if not result.unmet else "Completed with unmet constraints",
		"sessions_total": len(problem.sessions), "sessions_placed": len(problem.sessions) - result.unplaced,
		"soft_issues": result.soft_issues, "solver_status": f"{result.backend} {result.status}", "unmet": "\n".join(result.unmet) or None,
	}  # fmt: skip
