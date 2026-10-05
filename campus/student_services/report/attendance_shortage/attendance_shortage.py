"""M05-02 Attendance Shortage: students of a company and term who are in the medical band or short of attendance.

Limited to the companies the user is permitted for; thresholds come from each student's regulation.
"""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies
from campus.student_services.api import summarise, term_window
from campus.student_services.attendance_rules import ELIGIBLE


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 140},
		{"fieldname": "student_name", "label": _("Student Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "program", "label": _("Program"), "fieldtype": "Link", "options": "Program", "width": 160},
		{"fieldname": "overall_pct", "label": _("Overall %"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 120},
		{"fieldname": "short_courses", "label": _("Courses Below Minimum"), "fieldtype": "Small Text", "width": 300},
	]  # fmt: skip


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	window, conducted_cache, rows = term_window(filters.academic_term), {}, []
	for student, program in term_students(filters).items():
		summary = summarise(student, filters.academic_term, window, conducted_cache)
		if summary["status"] != ELIGIBLE:
			rows.append(report_row(student, program, summary))
	return sorted(rows, key=lambda row: (row["overall_pct"] is None, row["overall_pct"], row["student"]))


def term_students(filters):
	"""{student: program} for the active members of the term's course offerings of the company."""
	conditions = {
		"oc_company": filters.company, "academic_term": filters.academic_term, "group_based_on": "Course",
	}  # fmt: skip
	if filters.program:
		conditions["program"] = filters.program
	students = {}
	for group in frappe.get_list("Student Group", filters=conditions, fields=["name", "program"]):
		for student in frappe.get_all(
			"Student Group Student", {"parent": group.name, "active": 1}, pluck="student"
		):
			students.setdefault(student, group.program)
	return students


def report_row(student, program, summary):
	return {
		"student": student,
		"student_name": frappe.db.get_value("Student", student, "student_name"),
		"program": program,
		"overall_pct": summary["overall_pct"],
		"status": _(summary["status"]),
		"short_courses": ", ".join(
			f"{row['course']} ({row['pct']}%)" for row in summary["offerings"] if row["pct"] < summary["per_course_min_pct"]
		),
	}

