"""M15-01 Metric Drill-down: the source records behind a Metric Value, from its snapshot.

Limited to the companies the user is permitted for (Company User Permissions).
"""

import json

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "input", "label": _("Data Point"), "fieldtype": "Data", "width": 180},
		{"fieldname": "input_value", "label": _("Data Point Value"), "fieldtype": "Float", "width": 120},
		{"fieldname": "document_type", "label": _("Document Type"), "fieldtype": "Link", "options": "DocType", "width": 160},
		{"fieldname": "record", "label": _("Record"), "fieldtype": "Dynamic Link", "options": "document_type", "width": 260},
	]  # fmt: skip


def data(filters):
	metric = frappe.get_doc("Metric Value", filters.metric_value)
	metric.check_permission("read")
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and metric.company not in permitted:
		return []
	inputs = json.loads(metric.snapshot or "{}").get("inputs", {})
	return [
		{"input": key, "input_value": point["value"], "document_type": record["doctype"], "record": record["name"]}
		for key, point in inputs.items()
		for record in point["records"]
	]
