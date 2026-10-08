"""M07-03 Timetable Clash Checker: every hard-constraint breach of a Timetable's grid (faculty, room or section in two
places, unavailable faculty, lab and capacity rules, broken lab blocks), one row each with the slot and the parties.
Company and Timetable are required; a user limited to other companies by User Permissions sees nothing."""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies


def execute(filters=None):
	return columns(), clash_rows(frappe._dict(filters or {}))


def columns():
	return [
		{"fieldname": "rule", "label": _("Rule"), "fieldtype": "Data", "width": 170},
		{"fieldname": "day", "label": _("Day"), "fieldtype": "Data", "width": 100},
		{"fieldname": "period", "label": _("Period"), "fieldtype": "Int", "width": 70},
		{"fieldname": "subject", "label": _("Faculty / Room / Section"), "fieldtype": "Data", "width": 220},
		{"fieldname": "message", "label": _("Details"), "fieldtype": "Data", "width": 520},
	]


def clash_rows(filters):
	if not (filters.company and filters.timetable) or not allowed(filters.company):
		return []
	timetable = frappe.get_doc("Timetable", filters.timetable)
	if timetable.company != filters.company:
		return []
	return [violation._asdict() for violation in timetable.violations()]


def allowed(company):
	permitted = permitted_companies(frappe.session.user)
	return permitted is None or company in permitted
