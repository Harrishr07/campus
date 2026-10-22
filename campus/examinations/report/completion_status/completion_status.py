"""M05-15 Completion Status: the company's students by programme and batch, counted by the result of their latest
Completion Check. Limited to the companies the user is permitted for; the checks are read with the user's
permissions."""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies

COMPLETE, INCOMPLETE = "Complete", "Incomplete"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "program", "label": _("Program"), "fieldtype": "Link", "options": "Program", "width": 200},
		{"fieldname": "batch", "label": _("Batch"), "fieldtype": "Link", "options": "Academic Year", "width": 120},
		{"fieldname": "checked", "label": _("Checked"), "fieldtype": "Int", "width": 100},
		{"fieldname": "complete", "label": _("Complete"), "fieldtype": "Int", "width": 100},
		{"fieldname": "incomplete", "label": _("Incomplete"), "fieldtype": "Int", "width": 100},
	]


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if not filters.company or (permitted is not None and filters.company not in permitted):
		return []
	conditions = {"company": filters.company}
	for field in ("program", "batch"):
		if filters.get(field):
			conditions[field] = filters.get(field)
	checks = frappe.get_list(
		"Completion Check", conditions, ["student", "program", "batch", "result"], order_by="creation desc, name desc", limit=0
	)
	latest, rows = set(), {}
	for check in checks:
		if check.student in latest:
			continue
		latest.add(check.student)
		row = rows.setdefault(
			(check.program or "", check.batch or ""),
			{"program": check.program, "batch": check.batch, "checked": 0, "complete": 0, "incomplete": 0},
		)
		row["checked"] += 1
		row["complete" if check.result == COMPLETE else "incomplete"] += 1
	return [rows[key] for key in sorted(rows)]
