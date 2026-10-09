"""M17-06 Exam Eligibility (Withheld): the Hall Tickets withheld (attendance shortage, detention, debarment or exam
dues), with the reasons and the courses the student's Exam Registration marks not eligible.

Limited to the companies the user is permitted for and to the hall tickets the user may read."""

import frappe
from frappe import _

from campus.examinations import coe_reports


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters) if coe_reports.in_scope(filters.company) else []


def columns():
	return [
		{"fieldname": "exam_session", "label": _("Exam Session"), "fieldtype": "Link", "options": "Exam Session", "width": 140},
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 150},
		{"fieldname": "student_name", "label": _("Student Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "program", "label": _("Program"), "fieldtype": "Link", "options": "Program", "width": 160},
		{"fieldname": "withheld_reasons", "label": _("Reasons"), "fieldtype": "Small Text", "width": 260},
		{"fieldname": "not_eligible_courses", "label": _("Not Eligible Courses"), "fieldtype": "Small Text", "width": 220},
	]  # fmt: skip


def data(filters):
	conditions = {"company": filters.company, "status": "Withheld"}
	if filters.exam_session:
		conditions["exam_session"] = filters.exam_session
	tickets = frappe.get_list(
		"Hall Ticket", filters=conditions,
		fields=["exam_session", "student", "student_name", "program", "withheld_reasons", "exam_registration"], order_by="exam_session, student",
	)  # fmt: skip
	not_eligible = {}
	for row in frappe.get_all(
		"Exam Registration Course",
		{"parenttype": "Exam Registration", "parent": ["in", [t.exam_registration for t in tickets if t.exam_registration] or [""]],
			"eligibility": ["not in", ["", "Eligible"]]},
		["parent", "course"], order_by="parent, idx",
	):  # fmt: skip
		not_eligible.setdefault(row.parent, []).append(row.course)
	return [
		{**{k: t[k] for k in ("exam_session", "student", "student_name", "program", "withheld_reasons")},
		"not_eligible_courses": ", ".join(not_eligible.get(t.exam_registration, []))}
		for t in tickets
	]  # fmt: skip
