"""M05-04 TC Register: the transfer certificates issued by a company, with the student's leaving details.

Limited to the companies the user is permitted for. A cancelled TC is not listed.
"""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "certificate_number", "label": _("TC No"), "fieldtype": "Data", "width": 170},
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 130},
		{"fieldname": "student_name", "label": _("Student Name"), "fieldtype": "Data", "width": 170},
		{"fieldname": "leaving_date", "label": _("Date of Leaving"), "fieldtype": "Date", "width": 120},
		{"fieldname": "reason_for_leaving", "label": _("Reason"), "fieldtype": "Small Text", "width": 220},
		{"fieldname": "issued_on", "label": _("Issued On"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "verification_code", "label": _("Verification Code"), "fieldtype": "Data", "width": 130},
	]  # fmt: skip


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	return frappe.get_list(
		"Certificate Request",
		{"docstatus": 1, "company": filters.company, "is_transfer_certificate": 1},
		["certificate_number", "student", "student_name", "leaving_date", "reason_for_leaving", "issued_on", "verification_code"],
		order_by="issued_on desc", limit=0,
	)  # fmt: skip
