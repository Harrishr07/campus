"""M17-06 Malpractice Register: the Malpractice Reports (draft and submitted, never cancelled) with the category
and the committee decision.

Limited to the companies the user is permitted for and to the reports the user may read."""

import frappe
from frappe import _

from campus.examinations import coe_reports


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters) if coe_reports.in_scope(filters.company) else []


def columns():
	return [
		{"fieldname": "name", "label": _("Malpractice Report"), "fieldtype": "Link", "options": "Malpractice Report", "width": 150},
		{"fieldname": "exam_session", "label": _("Exam Session"), "fieldtype": "Link", "options": "Exam Session", "width": 140},
		{"fieldname": "exam_date", "label": _("Exam Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "course", "label": _("Course"), "fieldtype": "Link", "options": "Course", "width": 150},
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 150},
		{"fieldname": "student_name", "label": _("Student Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "category", "label": _("Category"), "fieldtype": "Data", "width": 160},
		{"fieldname": "committee_decision", "label": _("Committee Decision"), "fieldtype": "Data", "width": 150},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 90},
	]  # fmt: skip


def data(filters):
	conditions = {"company": filters.company, "docstatus": ["<", 2]}
	if filters.exam_session:
		conditions["exam_session"] = filters.exam_session
	rows = frappe.get_list(
		"Malpractice Report", filters=conditions,
		fields=["name", "exam_session", "exam_date", "course", "student", "student_name", "category", "committee_decision", "docstatus"],
		order_by="name",
	)  # fmt: skip
	for row in rows:
		row["status"] = _("Submitted") if row.pop("docstatus") == 1 else _("Draft")
	return rows
