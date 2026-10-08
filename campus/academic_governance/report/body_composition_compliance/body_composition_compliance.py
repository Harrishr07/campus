"""M02-01 Body Composition Compliance: every enabled body of the company that breaks its Body Type's composition
rule on the chosen date, one row per broken rule. Bodies are read through get_list, so User Permissions apply."""

import frappe
from frappe import _
from frappe.utils import today

from campus.academic_governance import composition


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		return columns(), []
	return columns(), violations(filters.company, filters.get("as_on_date") or today(), filters.get("body_type"))


def violations(company, on_date, body_type=None):
	query = {"company": company, "enabled": 1}
	if body_type:
		query["body_type"] = body_type
	rows = []
	for name in frappe.get_list("Body", query, pluck="name", order_by="name"):
		body = frappe.get_doc("Body", name)
		rules = frappe.get_cached_doc("Body Type", body.body_type).composition
		for shortfall in composition.composition_shortfalls(rules, body.members, on_date):
			rows.append(
				{
					"body": body.name,
					"body_type": body.body_type,
					"department": body.department,
					"category": _(shortfall.category),
					"rule": shortfall.rule,
					"in_office": shortfall.actual,
				}
			)
	return rows


def columns():
	return [
		{"fieldname": "body", "label": _("Body"), "fieldtype": "Link", "options": "Body", "width": 260},
		{"fieldname": "body_type", "label": _("Body Type"), "fieldtype": "Link", "options": "Body Type", "width": 170},
		{"fieldname": "department", "label": _("Department"), "fieldtype": "Link", "options": "Department", "width": 200},
		{"fieldname": "category", "label": _("Member Category"), "fieldtype": "Data", "width": 150},
		{"fieldname": "rule", "label": _("Rule"), "fieldtype": "Data", "width": 220},
		{"fieldname": "in_office", "label": _("In Office"), "fieldtype": "Int", "width": 90},
	]
