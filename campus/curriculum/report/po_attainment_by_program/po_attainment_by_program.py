"""M03-03 PO / PSO Attainment by Program / Batch: the PO and PSO levels of submitted PO Attainment Runs with the gap to
the target. Limited to the colleges the user is permitted for; runs are read with the user's permissions."""

import frappe
from frappe import _

from campus.curriculum.attainment import PO_RESULT, PO_RUN, check_company
from campus.curriculum.attainment_rules import gap, shown

FILTERS = ("program", "batch", "academic_year")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission(PO_RUN, "read", throw=True)
	check_company(filters.company)
	return columns(), rows(filters)


def rows(filters):
	conditions = {
		"docstatus": 1,
		"company": filters.company,
		**{f: filters[f] for f in FILTERS if filters.get(f)},
	}
	runs = {
		r.name: r
		for r in frappe.get_list(
			PO_RUN, filters=conditions, fields=["name", "program", "batch", "academic_year"], order_by="name"
		)
	}
	results = frappe.get_all(
		PO_RESULT, {"parenttype": PO_RUN, "parent": ["in", list(runs) or [""]]},
		["parent", "outcome_code", "courses", "mapped", "direct_level", "has_indirect", "indirect_level", "final_level", "target_level", "target_met"],
		order_by="parent, idx",
	)  # fmt: skip
	results = [frappe._dict(shown(r)) for r in results]
	return [
		{**r, "run": r.parent, "program": runs[r.parent].program, "batch": runs[r.parent].batch,
		"academic_year": runs[r.parent].academic_year, "gap": gap(r.final_level, r.target_level)}
		for r in results
	]  # fmt: skip


def columns():
	return [
		{
			"fieldname": "program",
			"label": _("Program"),
			"fieldtype": "Link",
			"options": "Program",
			"width": 150,
		},
		{
			"fieldname": "batch",
			"label": _("Batch"),
			"fieldtype": "Link",
			"options": "Academic Year",
			"width": 100,
		},
		{
			"fieldname": "academic_year",
			"label": _("Academic Year"),
			"fieldtype": "Link",
			"options": "Academic Year",
			"width": 110,
		},
		{"fieldname": "outcome_code", "label": _("PO / PSO"), "fieldtype": "Data", "width": 80},
		{"fieldname": "courses", "label": _("Courses"), "fieldtype": "Int", "width": 80},
		{"fieldname": "direct_level", "label": _("Direct"), "fieldtype": "Float", "width": 80},
		{"fieldname": "indirect_level", "label": _("Exit Survey"), "fieldtype": "Float", "width": 100},
		{"fieldname": "final_level", "label": _("Final"), "fieldtype": "Float", "width": 80},
		{"fieldname": "target_level", "label": _("Target"), "fieldtype": "Float", "width": 80},
		{"fieldname": "gap", "label": _("Gap"), "fieldtype": "Float", "width": 80},
		{"fieldname": "run", "label": _("Run"), "fieldtype": "Link", "options": PO_RUN, "width": 120},
	]
