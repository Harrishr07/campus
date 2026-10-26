"""M07-01 Shared filter handling of the faculty reports: company and academic year are required, and a user
limited to other companies by User Permissions sees nothing."""

import frappe

from campus.campus_platform.company_scope import permitted_companies


def report_filters(filters):
	"""The filters as a dict, or None when the user may not see the company (or a required filter is missing)."""
	filters = frappe._dict(filters or {})
	if not (filters.company and filters.academic_year):
		return None
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return None
	return filters


def department_column():
	return {
		"fieldname": "department",
		"label": frappe._("Department"),
		"fieldtype": "Link",
		"options": "Department",
		"width": 260,
	}
