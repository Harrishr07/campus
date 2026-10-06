"""M05-02 Student Services service API. Other modules call these, never the controllers (D7)."""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from campus.campus_platform.api import get_rule
from campus.student_services.attendance_rules import eligibility, overall_percentage, percentage

RULE_FIELDS = ("formula", "overall_min_pct", "medical_band_min_pct", "per_course_min_pct")


def attendance_summary(student, academic_term):
	"""Attendance eligibility of `student` in `academic_term` under the student's regulation.

	Not whitelisted: the Student read check alone would let any Student or Guardian role holder read a
	classmate's attendance over HTTP. Callers are Python code (the portal resolves its own student).

	Returns {"offerings": [{offering, course, conducted, attended, leave, pct}], "overall_pct",
	"per_course_min_pct", "status"}.
	conducted = Course Schedules of the offering dated in the term up to today; when the offering has no
	schedules, the distinct dates on which any student of it was marked. attended = the student's
	submitted Present records; leave = submitted Leave records backed by a submitted Student Leave
	Application, which count only in the medical band decision (see attendance_rules).
	"""
	frappe.has_permission("Student", "read", student, throw=True)
	return summarise(student, academic_term, term_window(academic_term), {})


def eligibility_status(student, academic_term):
	"""Eligible / Medical band / Shortage of `student` in the term, with no read check on the Student.

	For service code that has its own authorisation (the Result Run, which only a COE can start).
	"""
	return summarise(student, academic_term, term_window(academic_term), {})["status"]


def summarise(student, academic_term, window, conducted_cache):
	rule = rule_values(student)
	offerings = [
		offering_row(student, offering, window, conducted_cache) for offering in student_offerings(student, academic_term)
	]
	courses = [(row["conducted"], row["attended"], row["leave"]) for row in offerings]
	overall = overall_percentage(rule["formula"], [(c, a) for c, a, _leave in courses])
	return {
		"offerings": offerings,
		"overall_pct": None if overall is None else round(overall, 2),
		"per_course_min_pct": rule["per_course_min_pct"],
		"status": eligibility(rule, courses),
	}


def rule_values(student):
	doc = get_rule(student, "Attendance Rule")
	return {"formula": doc.formula, **{field: flt(doc.get(field)) for field in RULE_FIELDS[1:]}}


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


def offering_row(student, offering, window, conducted_cache):
	if offering.name not in conducted_cache:
		conducted_cache[offering.name] = conducted_periods(offering.name, window)
	conducted = conducted_cache[offering.name]
	attended, leave = marked_counts(student, offering.name, window)
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


def marked_counts(student, offering, window):
	"""(Present count, approved-leave count) of the student's submitted records for the offering."""
	attendance, leave = frappe.qb.DocType("Student Attendance"), frappe.qb.DocType("Student Leave Application")
	rows = (
		frappe.qb.from_(attendance)
		.left_join(leave)
		.on((leave.name == attendance.leave_application) & (leave.docstatus == 1))
		.select(attendance.status, leave.name.as_("approved_leave"))
		.where(attendance.student == student)
		.where(attendance.student_group == offering)
		.where(attendance.docstatus == 1)
		.where(attendance.date[window[0] : window[1]])
		.run(as_dict=True)
	)
	present = sum(1 for row in rows if row.status == "Present")
	on_leave = sum(1 for row in rows if row.status == "Leave" and row.approved_leave)
	return present, on_leave
