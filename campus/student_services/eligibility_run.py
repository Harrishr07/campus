"""M05-02 Attendance Eligibility Run: the frozen per-term attendance eligibility snapshot.

One Attendance Eligibility Run per (company, term, program, semester). Starting it queues a Bulk Run
(P1-T09) that computes each student with `summarise` and replaces the student's row, so running again
gives the same rows (idempotent). Once locked the snapshot is frozen: it cannot be re-run and a late
handler call is refused. Status labels: Eligible, Condonation (medical band), Detained (SA).
Guardians of students who are not Eligible get the "attendance.shortage" message.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from campus.campus_platform.bulk import run_bulk
from campus.student_services.api import summarise, term_window
from campus.student_services.attendance_rules import ELIGIBLE, MEDICAL_BAND

DOCTYPE, ROW = "Attendance Eligibility Run", "Attendance Eligibility Row"
RUN_TYPE = "Attendance Eligibility Run"
HANDLER = "campus.student_services.eligibility_run.run_student"
LABELS = {ELIGIBLE: "Eligible", MEDICAL_BAND: "Condonation", "Shortage": "Detained (SA)"}
COUNT_FIELDS = {"Eligible": "eligible_count", "Condonation": "condonation_count", "Detained (SA)": "detained_count"}
ALERT_EVENT = "attendance.shortage"
SAVEPOINT = "eligibility_alert"
IN_PROGRESS = ("Queued", "Running")


def run_key(doc):
	return "|".join([doc.company, doc.academic_term, doc.program or "", str(doc.semester or "")])


def term_students(doc):
	"""{student: program}: active members of the term's course offerings of the company, narrowed by the run's filters."""
	conditions = {"oc_company": doc.company, "academic_term": doc.academic_term, "group_based_on": "Course"}
	if doc.program:
		conditions["program"] = doc.program
	if doc.semester:
		conditions["oc_semester"] = doc.semester
	students = {}
	for group in frappe.get_all("Student Group", conditions, ["name", "program"], order_by="name"):
		for student in frappe.get_all("Student Group Student", {"parent": group.name, "active": 1}, pluck="student"):
			students.setdefault(student, group.program)
	return students


def start(doc):
	"""Queue the run of `doc`; returns the Bulk Run name. Refused once locked or while a run is in progress."""
	doc.check_permission("write")
	doc.reload()
	if doc.locked:
		frappe.throw(_("{0} is locked and cannot be run again.").format(doc.name))
	if doc.bulk_run and frappe.db.get_value("Bulk Run", doc.bulk_run, "status") in IN_PROGRESS:
		frappe.throw(_("{0} is already running.").format(doc.name))
	students = term_students(doc)
	keep = list(students) or [""]
	frappe.db.delete(ROW, {"parent": doc.name, "student": ["not in", keep]})
	bulk_run = run_bulk(RUN_TYPE, sorted(students), HANDLER, parameters={"run": doc.name})
	doc.db_set({"bulk_run": bulk_run, "run_on": now_datetime()})
	return bulk_run


def lock(doc):
	"""Freeze the snapshot. Needs the Dean Academics or System Manager role and no run in progress."""
	frappe.only_for(("Dean Academics", "System Manager"))
	doc.reload()
	if doc.locked:
		return
	if doc.bulk_run and frappe.db.get_value("Bulk Run", doc.bulk_run, "status") in IN_PROGRESS:
		frappe.throw(_("{0} is still running; lock it when the run has finished.").format(doc.name))
	if not doc.rows:
		frappe.throw(_("{0} has no results to lock; run it first.").format(doc.name))
	doc.db_set({"locked": 1, "locked_by": frappe.session.user, "locked_on": now_datetime()})


def run_student(student, run):
	"""Bulk handler: (re)compute one student's row of the run. DB-only, no commit."""
	name = run.get_parameters()["run"]
	doc = frappe.db.get_value(
		DOCTYPE, name, ["locked", "academic_term", "send_guardian_alerts"], as_dict=True, for_update=True
	)
	if doc.locked:
		frappe.throw(_("{0} is locked.").format(name))
	summary = summarise(student, doc.academic_term, term_window(doc.academic_term), {})
	status = LABELS[summary["status"] if summary["condoned"] else summary["band_status"]]
	write_row(name, student, summary, status)
	refresh_counts(name)
	if doc.send_guardian_alerts and status != "Eligible":
		alert_guardians(student, summary)


def write_row(name, student, summary, status):
	frappe.db.delete(ROW, {"parent": name, "student": student})
	row = frappe.get_doc(
		{
			"doctype": ROW, "name": frappe.generate_hash(length=10), "parent": name, "parenttype": DOCTYPE,
			"parentfield": "rows", "idx": frappe.db.count(ROW, {"parent": name}) + 1, "student": student,
			"student_name": frappe.db.get_value("Student", student, "student_name"),
			"program": program_of(student, summary), "overall_pct": summary["overall_pct"], "status": status,
			"condoned": 1 if summary["condoned"] else 0, "shortage_summary": shortage_summary(summary),
		}
	)  # fmt: skip
	row.set_user_and_timestamp()
	row.db_insert()


def program_of(student, summary):
	offering = summary["offerings"][0]["offering"] if summary["offerings"] else None
	return frappe.db.get_value("Student Group", offering, "program") if offering else None


def shortage_summary(summary):
	"""The courses below the per-course minimum (or, with none, below the overall minimum), e.g. "ATT A (70%)"."""
	threshold = summary["per_course_min_pct"] or summary["overall_min_pct"]
	return ", ".join(f"{row['course']} ({row['pct']:g}%)" for row in summary["offerings"] if row["pct"] < threshold)


def refresh_counts(name):
	counts = dict(
		frappe.db.sql("select status, count(*) from `tabAttendance Eligibility Row` where parent = %s group by status", name)
	)
	frappe.db.set_value(DOCTYPE, name, {field: counts.get(status, 0) for status, field in COUNT_FIELDS.items()}, update_modified=False)


def alert_guardians(student, summary):
	"""Best effort: a messaging problem must never fail the student's row."""
	guardians = frappe.get_all("Student Guardian", {"parent": student, "parenttype": "Student"}, pluck="guardian")
	if not (guardians and frappe.db.exists("Message Template", {"event_key": ALERT_EVENT, "enabled": 1})):
		return
	from campus.campus_messaging.api import send

	frappe.db.savepoint(SAVEPOINT)
	try:
		send(
			ALERT_EVENT, frappe.get_doc("Student", student), [f"Guardian:{g}" for g in guardians if g],
			{"percentage": flt(summary["overall_pct"]), "dedupe_token": summary["term"]},
		)
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.log_error(title="Attendance shortage alert failed")
