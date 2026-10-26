"""M17-06 Valuation Difference: per script (dummy number) with both valuations submitted, the first and second
totals, their difference and the third valuation when one was made (campus.examinations.valuation sends a script to
a third valuation above the Exam Rule Set threshold). Dummy numbers only; nothing names a student.

Limited to the companies the user is permitted for and to the Valuation Entries the user may read."""

import frappe
from frappe import _
from frappe.utils import flt

from campus.examinations import coe_reports


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters) if coe_reports.in_scope(filters.company) else []


def columns():
	return [
		{"fieldname": "exam_session", "label": _("Exam Session"), "fieldtype": "Link", "options": "Exam Session", "width": 130},
		{"fieldname": "course", "label": _("Course"), "fieldtype": "Link", "options": "Course", "width": 150},
		{"fieldname": "dummy_number", "label": _("Dummy Number"), "fieldtype": "Data", "width": 130},
		{"fieldname": "first", "label": _("First Valuation"), "fieldtype": "Float", "width": 120},
		{"fieldname": "second", "label": _("Second Valuation"), "fieldtype": "Float", "width": 130},
		{"fieldname": "difference", "label": _("Difference"), "fieldtype": "Float", "width": 100},
		{"fieldname": "third", "label": _("Third Valuation"), "fieldtype": "Float", "width": 120},
	]  # fmt: skip


def data(filters):
	conditions = {"company": filters.company}
	if filters.exam_session:
		conditions["name"] = filters.exam_session
	sessions = frappe.get_all(
		"Exam Session", filters=conditions, pluck="name"
	)  # the company is checked by in_scope
	entries = frappe.get_list(
		"Valuation Entry", filters={"exam_session": ["in", sessions or [""]], "docstatus": 1},
		fields=["exam_session", "course", "dummy_number", "valuation_round", "total"],
	)  # fmt: skip
	scripts = {}
	for entry in entries:
		scripts.setdefault((entry.exam_session, entry.course, entry.dummy_number), {})[
			str(entry.valuation_round)
		] = flt(entry.total)
	out = []
	for (session, course, dummy), marks in sorted(scripts.items()):
		if "1" in marks and "2" in marks:
			out.append(
				{"exam_session": session, "course": course, "dummy_number": dummy, "first": marks["1"], "second": marks["2"],
				"difference": abs(marks["1"] - marks["2"]), "third": marks.get("3")}
			)  # fmt: skip
	return out
