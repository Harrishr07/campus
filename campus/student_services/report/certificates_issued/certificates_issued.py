"""M05-04 Certificates Issued: submitted Certificate Requests of a company, by type and period.

Limited to the companies the user is permitted for.
"""

import frappe
from frappe import _
from frappe.utils import add_days

from campus.campus_platform.company_scope import permitted_companies


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "certificate_number", "label": _("Certificate No"), "fieldtype": "Data", "width": 170},
		{"fieldname": "certificate_type", "label": _("Type"), "fieldtype": "Link", "options": "Certificate Type", "width": 160},
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 130},
		{"fieldname": "student_name", "label": _("Student Name"), "fieldtype": "Data", "width": 170},
		{"fieldname": "issued_on", "label": _("Issued On"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "purpose", "label": _("Purpose"), "fieldtype": "Data", "width": 200},
		{"fieldname": "verification_code", "label": _("Verification Code"), "fieldtype": "Data", "width": 130},
		{"fieldname": "name", "label": _("Request"), "fieldtype": "Link", "options": "Certificate Request", "width": 130},
	]  # fmt: skip


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	conditions = {"docstatus": 1, "company": filters.company}
	if filters.certificate_type:
		conditions["certificate_type"] = filters.certificate_type
	if filters.from_date:
		conditions["issued_on"] = [">=", filters.from_date]
	if filters.to_date:
		conditions["issued_on"] = ["<", add_days(filters.to_date, 1)]
	if filters.from_date and filters.to_date:
		conditions["issued_on"] = ["between", [filters.from_date, add_days(filters.to_date, 1)]]
	return frappe.get_list(
		"Certificate Request", conditions,
		["name", "certificate_number", "certificate_type", "student", "student_name", "issued_on", "purpose", "verification_code"],
		order_by="issued_on desc", limit=0,
	)  # fmt: skip
