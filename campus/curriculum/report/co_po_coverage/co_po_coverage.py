"""M03-02 CO-PO Coverage: per PO / PSO of a curriculum's programme, the total correlation and the number of courses
mapping it across the curriculum's approved CO-PO Matrices. An outcome with zero total is flagged "Not mapped" and
listed in the report message (AC1). Limited to the colleges the user is permitted for; matrices are read with the
user's permissions.
"""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies
from campus.curriculum.outcomes import coverage


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("CO-PO Matrix", "read", throw=True)
	permitted = permitted_companies(frappe.session.user)
	if not filters.company or (permitted is not None and filters.company not in permitted):
		frappe.throw(_("Choose a college you are permitted for."), frappe.PermissionError)
	if not filters.curriculum:
		frappe.throw(_("Choose a curriculum."))
	program = frappe.db.get_value("Curriculum", filters.curriculum, "program")
	if frappe.db.get_value("Program", program, "oc_company") != filters.company:
		frappe.throw(
			_("{0} is not a curriculum of {1}.").format(
				frappe.bold(filters.curriculum), frappe.bold(filters.company)
			)
		)
	rows = coverage(filters.curriculum, read=frappe.get_list)
	unmapped = [row.outcome_code for row in rows if not row.total_correlation]
	message = (
		_("Outcomes with zero total correlation across {0}: {1}.").format(
			filters.curriculum, ", ".join(unmapped)
		)
		if unmapped
		else None
	)
	return columns(), rows, message


def columns():
	return [
		{"fieldname": "outcome_code", "label": _("PO / PSO"), "fieldtype": "Data", "width": 90},
		{
			"fieldname": "outcome",
			"label": _("Outcome"),
			"fieldtype": "Dynamic Link",
			"options": "outcome_type",
			"width": 200,
		},
		{"fieldname": "outcome_type", "label": _("Type"), "fieldtype": "Data", "width": 170},
		{"fieldname": "statement", "label": _("Statement"), "fieldtype": "Data", "width": 300},
		{"fieldname": "courses", "label": _("Courses Mapping"), "fieldtype": "Int", "width": 130},
		{"fieldname": "total_correlation", "label": _("Total Correlation"), "fieldtype": "Int", "width": 130},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
	]
