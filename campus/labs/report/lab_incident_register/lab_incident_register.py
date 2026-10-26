"""M12-05 Lab Incident Register: incidents by laboratory, limited to the companies the user may read."""

import frappe
from frappe import _
from frappe.utils import add_days

from campus.labs.report_scope import scoped_companies


def execute(filters=None):
	filters = frappe._dict(filters or {})
	companies = scoped_companies(filters.company)
	if companies is not None and not companies:
		return columns(), []
	conditions = [
		[key, "=", filters[key]] for key in ("laboratory", "severity", "status") if filters.get(key)
	]
	if companies is not None:
		conditions.append(["company", "in", companies])
	if filters.from_date:
		conditions.append(["incident_time", ">=", filters.from_date])
	if filters.to_date:
		conditions.append(["incident_time", "<", add_days(filters.to_date, 1)])
	fields = [
		"name",
		"laboratory",
		"company",
		"incident_time",
		"incident_type",
		"severity",
		"status",
		"reported_by",
		"action_taken",
	]
	return columns(), frappe.get_all("Lab Incident", conditions, fields, order_by="incident_time desc, name")


def columns():
	return [
		{"fieldname": "name", "label": _("Incident"), "fieldtype": "Link", "options": "Lab Incident", "width": 140},
		{"fieldname": "laboratory", "label": _("Laboratory"), "fieldtype": "Link", "options": "Laboratory", "width": 170},
		{"fieldname": "company", "label": _("Company"), "fieldtype": "Link", "options": "Company", "width": 150},
		{"fieldname": "incident_time", "label": _("When"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "incident_type", "label": _("Type"), "fieldtype": "Data", "width": 130},
		{"fieldname": "severity", "label": _("Severity"), "fieldtype": "Data", "width": 90},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 80},
		{"fieldname": "reported_by", "label": _("Reported By"), "fieldtype": "Link", "options": "Employee", "width": 120},
		{"fieldname": "action_taken", "label": _("Action Taken"), "fieldtype": "Data", "width": 260},
	]  # fmt: skip
