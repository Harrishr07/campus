"""M17-06 Valuation Progress: per Valuation Allocation (course, round, examiner), the scripts allocated, valued
(a submitted Valuation Entry on the allocation) and pending (void scripts are never valued), and whether it is past
its deadline with scripts pending. Dummy numbers only; nothing names a student.

Limited to the companies the user is permitted for and to the allocations the user may read."""

import frappe
from frappe import _
from frappe.utils import getdate, today

from campus.examinations import coe_reports


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters) if coe_reports.in_scope(filters.company) else []


def columns():
	return [
		{"fieldname": "allocation", "label": _("Allocation"), "fieldtype": "Link", "options": "Valuation Allocation", "width": 130},
		{"fieldname": "exam_session", "label": _("Exam Session"), "fieldtype": "Link", "options": "Exam Session", "width": 130},
		{"fieldname": "course", "label": _("Course"), "fieldtype": "Link", "options": "Course", "width": 150},
		{"fieldname": "valuation_round", "label": _("Round"), "fieldtype": "Data", "width": 70},
		{"fieldname": "examiner", "label": _("Examiner"), "fieldtype": "Link", "options": "User", "width": 180},
		{"fieldname": "deadline", "label": _("Deadline"), "fieldtype": "Date", "width": 110},
		{"fieldname": "scripts", "label": _("Scripts"), "fieldtype": "Int", "width": 80},
		{"fieldname": "valued", "label": _("Valued"), "fieldtype": "Int", "width": 80},
		{"fieldname": "pending", "label": _("Pending"), "fieldtype": "Int", "width": 80},
		{"fieldname": "overdue", "label": _("Overdue"), "fieldtype": "Check", "width": 80},
	]  # fmt: skip


def data(filters):
	conditions = {"company": filters.company}
	if filters.exam_session:
		conditions["exam_session"] = filters.exam_session
	allocations = frappe.get_list(
		"Valuation Allocation", filters=conditions,
		fields=["name", "exam_session", "course", "valuation_round", "examiner", "deadline"], order_by="name",
	)  # fmt: skip
	names = [a.name for a in allocations] or [""]
	scripts, valued = {}, {}
	for row in frappe.get_all(
		"Valuation Allocation Script",
		{"parenttype": "Valuation Allocation", "parent": ["in", names]},
		["parent", "dummy_number"],
	):
		scripts.setdefault(row.parent, set()).add(row.dummy_number)
	for row in frappe.get_all(
		"Valuation Entry", {"allocation": ["in", names], "docstatus": 1}, ["allocation", "dummy_number"]
	):
		valued.setdefault(row.allocation, set()).add(row.dummy_number)
	every = set().union(*scripts.values()) if scripts else set()
	void = set(
		frappe.get_all(
			"Dummy Number Map", {"dummy_number": ["in", list(every) or [""]], "void": 1}, pluck="dummy_number"
		)
	)
	out = []
	for a in allocations:
		allocated, done = scripts.get(a.name, set()), valued.get(a.name, set())
		pending = len(allocated - done - void)
		overdue = int(bool(pending and a.deadline and getdate(a.deadline) < getdate(today())))
		out.append({"allocation": a.name, **{k: a[k] for k in ("exam_session", "course", "valuation_round", "examiner", "deadline")},
			"scripts": len(allocated), "valued": len(allocated & done), "pending": pending, "overdue": overdue})  # fmt: skip
	return out
