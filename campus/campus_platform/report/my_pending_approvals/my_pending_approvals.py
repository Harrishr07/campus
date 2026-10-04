"""M17-03 My Pending Approvals: requests the current user can act on now, as approver or delegate.

Rows are limited to the companies the user is permitted for (User Permission on Company).
"""

import frappe
from frappe import _

from campus.campus_platform.approval_access import pending_approvals


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), pending_approvals(frappe.session.user, filters.company)


def columns():
	return [
		{
			"fieldname": "request",
			"label": _("Request"),
			"fieldtype": "Link",
			"options": "Approval Request",
			"width": 130,
		},
		{
			"fieldname": "reference_doctype",
			"label": _("Document Type"),
			"fieldtype": "Link",
			"options": "DocType",
			"width": 160,
		},
		{
			"fieldname": "reference_name",
			"label": _("Document"),
			"fieldtype": "Dynamic Link",
			"options": "reference_doctype",
			"width": 160,
		},
		{
			"fieldname": "company",
			"label": _("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"width": 180,
		},
		{"fieldname": "current_level", "label": _("Level"), "fieldtype": "Int", "width": 70},
		{"fieldname": "due_at", "label": _("Due At"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "overdue", "label": _("Overdue"), "fieldtype": "Check", "width": 80},
		{
			"fieldname": "on_behalf_of",
			"label": _("On Behalf Of"),
			"fieldtype": "Link",
			"options": "User",
			"width": 180,
		},
	]
