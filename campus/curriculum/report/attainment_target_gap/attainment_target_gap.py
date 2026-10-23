"""M03-03 Attainment Target Gap: every CO, PO and PSO of the submitted attainment runs whose final level is below its
target, with the gap (outcomes not assessed or not mapped have no level and are left out). Limited to the colleges the
user is permitted for; runs are read with the user's permissions."""

import frappe
from frappe import _

from campus.curriculum.attainment import CO_RESULT, CO_RUN, PO_RESULT, PO_RUN, check_company
from campus.curriculum.attainment_rules import gap


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission(CO_RUN, "read", throw=True)
	check_company(filters.company)
	return columns(), [
		*below_target(filters, CO_RUN, CO_RESULT, "CO", ("co_code", "course", "assessed")),
		*below_target(filters, PO_RUN, PO_RESULT, "PO", ("outcome_code", "program", "mapped")),
	]


def below_target(filters, doctype, result_doctype, level, fields):
	code_field, scope_field, has_level = fields
	if not frappe.has_permission(doctype, "read"):
		return []
	conditions = {"docstatus": 1, "company": filters.company, **{f: filters[f] for f in ("program", "academic_year") if filters.get(f)}}
	fields = ["name", scope_field, "batch"] + (["course_offering"] if doctype == CO_RUN else [])
	runs = {r.name: r for r in frappe.get_list(doctype, filters=conditions, fields=fields, order_by="name")}
	results = frappe.get_all(
		result_doctype, {"parenttype": doctype, "parent": ["in", list(runs) or [""]], has_level: 1, "target_met": 0},
		["parent", f"{code_field} as outcome_code", "final_level", "target_level"], order_by="parent, idx",
	)  # fmt: skip
	return [
		{**r, "level": level, "run": r.parent, "run_type": doctype, "batch": runs[r.parent].batch,
		"scope": runs[r.parent].get("course_offering") or runs[r.parent].get(scope_field), "gap": gap(r.final_level, r.target_level)}
		for r in results
	]  # fmt: skip


def columns():
	return [
		{"fieldname": "level", "label": _("Level"), "fieldtype": "Data", "width": 60},
		{"fieldname": "scope", "label": _("Offering / Program"), "fieldtype": "Data", "width": 200},
		{"fieldname": "batch", "label": _("Batch"), "fieldtype": "Link", "options": "Academic Year", "width": 100},
		{"fieldname": "outcome_code", "label": _("Outcome"), "fieldtype": "Data", "width": 80},
		{"fieldname": "final_level", "label": _("Final"), "fieldtype": "Float", "width": 80},
		{"fieldname": "target_level", "label": _("Target"), "fieldtype": "Float", "width": 80},
		{"fieldname": "gap", "label": _("Gap"), "fieldtype": "Float", "width": 80},
		{"fieldname": "run_type", "label": _("Run Type"), "fieldtype": "Data", "hidden": 1},
		{"fieldname": "run", "label": _("Run"), "fieldtype": "Dynamic Link", "options": "run_type", "width": 120},
	]
