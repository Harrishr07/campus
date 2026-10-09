"""M05-02 Student Services service API. Other modules call these, never the controllers (D7)."""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from campus.campus_platform.api import get_rule
from campus.student_services.attendance_rules import (
	ATTENDED,
	ELIGIBLE,
	MEDICAL_BAND,
	MEDICAL_LEAVE,
	bucket,
	eligibility,
	overall_percentage,
	percentage,
)
from campus.student_services.attendance_rules import attendance_marks as marks_for_pct
from campus.student_services import mentors as allocation
from campus.student_services.onboarding import create_for_student as create_onboarding  # noqa: F401  (public API)
from campus.student_services.onboarding import mark_item_done
from campus.student_services.student_records import (  # noqa: F401  (public API)
	on_break,
	pending_bridge_courses,
	students_on_break,
	withdrawal_code,
)

RULE_FIELDS = ("overall_min_pct", "medical_band_min_pct", "per_course_min_pct")


def attendance_summary(student, academic_term):
	"""Attendance eligibility of `student` in `academic_term` under the student's regulation.

	Not whitelisted: the Student read check alone would let any Student or Guardian role holder read a
	classmate's attendance over HTTP. Callers are Python code (the portal resolves its own student).

	Returns {"offerings": [{offering, course, conducted, attended, leave, pct}], "overall_pct",
	"per_course_min_pct", "status", "band_status", "condoned"}. `band_status` is the status before an
	approved Condonation Request is applied; `condoned` says one turned the Medical band into Eligible.
	conducted = Course Schedules of the offering dated in the term up to today; when the offering has no
	schedules, the distinct dates on which any student of it was marked. attended = the student's
	submitted Present records plus On Duty leave when the rule counts it; leave = Leave records backed by
	a submitted Medical Student Leave Application when the rule counts it, which count only in the medical
	band decision (see attendance_rules).
	"""
	frappe.has_permission("Student", "read", student, throw=True)
	return summarise(student, academic_term, term_window(academic_term), {})


def eligibility_status(student, academic_term):
	"""Eligible / Medical band / Shortage of `student` in the term, with no read check on the Student.

	An approved (submitted) Condonation Request of the student for the term turns a Medical band into Eligible.

	For service code that has its own authorisation (the Result Run, which only a COE can start).
	"""
	return summarise(student, academic_term, term_window(academic_term), {})["status"]


def attendance_snapshot(student, academic_term, company):
	"""Eligible / Shortage of `student` in the term from the frozen Attendance Eligibility Run, or None.

	Only locked runs of the company count (the latest locked one holding the student). "Detained (SA)" is a
	Shortage; "Condonation" (medical band) is Eligible only once a Condonation Request of the student for the
	term is approved (submitted), else a Shortage. None when no locked run has a row for the student.
	No read check on the Student: for service code with its own authorisation (exam registration).
	"""
	run, row = frappe.qb.DocType("Attendance Eligibility Run"), frappe.qb.DocType("Attendance Eligibility Row")
	rows = (
		frappe.qb.from_(run)
		.join(row)
		.on((row.parent == run.name) & (row.parenttype == "Attendance Eligibility Run"))
		.select(row.status)
		.where((run.company == company) & (run.academic_term == academic_term) & (run.locked == 1))
		.where(row.student == student)
		.orderby(run.locked_on, order=frappe.qb.desc)
		.orderby(run.name, order=frappe.qb.desc)
		.limit(1)
		.run()
	)
	if not rows:
		return None
	status = rows[0][0]
	if status == "Eligible" or (status == "Condonation" and has_condonation(student, academic_term)):
		return ELIGIBLE
	return "Shortage"


def attendance_marks(student, offering):
	"""CIA attendance marks of `student` in the course offering (Student Group), by the regulation's mark bands.

	Not whitelisted, like attendance_summary: callers are Python code (Phase 2 CIA).
	Returns {"offering", "conducted", "attended", "pct", "marks"}; marks is 0 under a regulation without bands.
	"""
	term = frappe.db.get_value("Student Group", offering, "academic_term")
	rule = rule_values(student)
	row = offering_row(student, frappe._dict(name=offering, course=None), term_window(term), {}, rule)
	row["marks"] = marks_for_pct(rule["bands"], row["pct"])
	return {key: row[key] for key in ("offering", "conducted", "attended", "pct", "marks")}


def summarise(student, academic_term, window, conducted_cache):
	rule = rule_values(student)
	offerings = [
		offering_row(student, offering, window, conducted_cache, rule)
		for offering in student_offerings(student, academic_term)
	]
	courses = [(row["conducted"], row["attended"], row["leave"]) for row in offerings]
	overall = overall_percentage(rule["formula"], [(c, a) for c, a, _leave in courses])
	status = eligibility(rule, courses)
	condoned = status == MEDICAL_BAND and has_condonation(student, academic_term)
	return {
		"offerings": offerings,
		"overall_pct": None if overall is None else round(overall, 2),
		"term": academic_term,
		"per_course_min_pct": rule["per_course_min_pct"],
		"overall_min_pct": rule["overall_min_pct"],
		"status": ELIGIBLE if condoned else status,
		"band_status": status,
		"condoned": condoned,
	}


def has_condonation(student, academic_term):
	return bool(
		frappe.db.exists("Condonation Request", {"student": student, "academic_term": academic_term, "docstatus": 1})
	)


def rule_values(student):
	doc = get_rule(student, "Attendance Rule")
	return {
		"formula": doc.formula,
		**{field: flt(doc.get(field)) for field in RULE_FIELDS},
		"od_counts": doc.od_counts,
		"medical_counts": doc.medical_counts,
		"condonation_fee": flt(doc.condonation_fee),
		"bands": [(b.from_pct, b.to_pct, flt(b.marks)) for b in doc.mark_bands],
	}


def student_terms(student):
	"""Academic Terms in which the student is an active member of a course offering, newest first."""
	group, member = frappe.qb.DocType("Student Group"), frappe.qb.DocType("Student Group Student")
	term = frappe.qb.DocType("Academic Term")
	return (
		frappe.qb.from_(group)
		.join(member)
		.on(member.parent == group.name)
		.join(term)
		.on(term.name == group.academic_term)
		.select(term.name, term.term_start_date)
		.where(group.group_based_on == "Course")
		.where(member.student == student)
		.where(member.active == 1)
		.groupby(term.name, term.term_start_date)
		.orderby(term.term_start_date, order=frappe.qb.desc)
		.run(as_dict=True)
	)


def latest_attendance(student):
	"""(academic term, overall attendance %) of the student's latest term, or (None, None) without a term or a
	percentage. No read check on the Student: for service code with its own authorisation (renewal rules)."""
	terms = student_terms(student)
	if not terms:
		return None, None
	return terms[0].name, summarise(student, terms[0].name, term_window(terms[0].name), {})["overall_pct"]


def term_window(academic_term):
	"""(first day, last day counted): the term start and the earlier of term end and today."""
	start, end = frappe.db.get_value("Academic Term", academic_term, ["term_start_date", "term_end_date"])
	if not (start and end):
		frappe.throw(_("Academic Term {0} has no start and end dates.").format(frappe.bold(academic_term)))
	return getdate(start), min(getdate(end), getdate(today()))


def student_offerings(student, academic_term):
	"""Course-based Student Groups of the term in which the student is an active member."""
	group, member = frappe.qb.DocType("Student Group"), frappe.qb.DocType("Student Group Student")
	return (
		frappe.qb.from_(group)
		.join(member)
		.on(member.parent == group.name)
		.select(group.name, group.course)
		.where(group.group_based_on == "Course")
		.where(group.academic_term == academic_term)
		.where(member.student == student)
		.where(member.active == 1)
		.orderby(group.name)
		.run(as_dict=True)
	)


def offering_row(student, offering, window, conducted_cache, rule):
	if offering.name not in conducted_cache:
		conducted_cache[offering.name] = conducted_periods(offering.name, window)
	conducted = conducted_cache[offering.name]
	attended, leave = marked_counts(student, offering.name, window, rule)
	return {
		"offering": offering.name,
		"course": offering.course,
		"conducted": conducted,
		"attended": attended,
		"leave": leave,
		"pct": round(percentage(attended, conducted), 2),
	}


def conducted_periods(offering, window):
	scheduled = frappe.db.count(
		"Course Schedule", {"student_group": offering, "schedule_date": ["between", window]}
	)
	if scheduled:
		return scheduled
	marked_dates = frappe.get_all(
		"Student Attendance",
		filters={"student_group": offering, "docstatus": 1, "date": ["between", window]},
		pluck="date",
	)
	return len(set(marked_dates))


def marked_counts(student, offering, window, rule):
	"""(attended, medical-leave) counts of the student's submitted records for the offering, per the rule."""
	attendance, leave = frappe.qb.DocType("Student Attendance"), frappe.qb.DocType("Student Leave Application")
	rows = (
		frappe.qb.from_(attendance)
		.left_join(leave)
		.on((leave.name == attendance.leave_application) & (leave.docstatus == 1))
		.select(attendance.status, leave.oc_leave_kind)
		.where(attendance.student == student)
		.where(attendance.student_group == offering)
		.where(attendance.docstatus == 1)
		.where(attendance.date[window[0] : window[1]])
		.run(as_dict=True)
	)
	buckets = [bucket(row.status, row.oc_leave_kind, rule) for row in rows]
	return buckets.count(ATTENDED), buckets.count(MEDICAL_LEAVE)


ID_CARD_FORMAT = "Student ID Card"


@frappe.whitelist(methods=["POST"])
def allocate_mentors(student_group=None, program=None, batch=None, mentors=None, per_mentor=None):
	"""HOD/Dean tool (M05-07): spread the students of a group (or of a program and batch) evenly over mentors.

	`mentors` is an optional list of Employee ids (JSON list accepted); each must hold the MENTOR position.
	Left out, every active MENTOR position holder is used. Round-robin in register-number order, so the order of
	`mentors` decides who gets the extra student when the split is uneven. `per_mentor` is an optional ceiling:
	the call fails if the cohort would need more. Returns {mentor: [students]}.
	"""
	return allocation.allocate(student_group, program, batch, mentors, per_mentor)


@frappe.whitelist(methods=["POST"])
def issue_id_card(student):
	"""Issue a verifiable Student ID Card (photo + QR); returns its code and verification URL."""
	from campus.campus_platform import verification

	frappe.has_permission("Student", "write", student, throw=True)
	record = verification.issue(frappe.get_doc("Student", student), ID_CARD_FORMAT)
	mark_item_done(student, "ID-CARD")
	return {"code": record.code, "url": verification.verification_url(record.code)}
