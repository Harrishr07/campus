"""M17-06 Arrear List: the company's students (optionally of one program) with an outstanding arrear - a course
whose latest published outcome is not a Pass (campus.examinations.arrears.arrear_courses: Fail, SA, AB or WD).

Limited to the companies the user is permitted for and to the results the user may read."""

import frappe
from frappe import _

from campus.examinations import coe_reports
from campus.examinations.arrears import arrear_courses


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters) if coe_reports.in_scope(filters.company) else []


def columns():
	return [
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 150},
		{"fieldname": "student_name", "label": _("Student Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "program", "label": _("Program"), "fieldtype": "Link", "options": "Program", "width": 180},
		{"fieldname": "arrear_count", "label": _("Arrears"), "fieldtype": "Int", "width": 80},
		{"fieldname": "courses", "label": _("Arrear Courses"), "fieldtype": "Small Text", "width": 300},
	]  # fmt: skip


def data(filters):
	sessions = frappe.get_list(
		"Exam Session", filters={"company": filters.company, "status": coe_reports.PUBLISHED}, pluck="name"
	)
	programs = [filters.program] if filters.program else None
	students = {}
	for result in coe_reports.published_results(sessions, programs, lister=frappe.get_list):
		students.setdefault(result.student, result)
	out = []
	for student in sorted(students):
		courses = arrear_courses(student)
		if courses:
			result = students[student]
			out.append(
				{"student": student, "student_name": result.student_name, "program": result.program,
				"arrear_count": len(courses), "courses": ", ".join(courses)}
			)  # fmt: skip
	return out
