"""M05-05 Concession Register: the fee concessions of a company, their approval state and the invoice they discounted.

Rows are those the user may read (User Permissions apply); a cancelled concession is listed as Cancelled.
"""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies

FIELDS = [
	"name", "student", "student_name", "academic_year", "fee_category", "concession_type", "percent", "amount", "status",
	"applied_invoice", "discount_amount", "docstatus", "reason",
]  # fmt: skip


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "name", "label": _("Concession"), "fieldtype": "Link", "options": "Fee Concession", "width": 140},
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 130},
		{"fieldname": "student_name", "label": _("Student Name"), "fieldtype": "Data", "width": 170},
		{"fieldname": "academic_year", "label": _("Academic Year"), "fieldtype": "Link", "options": "Academic Year", "width": 110},
		{"fieldname": "fee_category", "label": _("Fee Category"), "fieldtype": "Link", "options": "Fee Category", "width": 120},
		{"fieldname": "concession", "label": _("Concession"), "fieldtype": "Data", "width": 110},
		{"fieldname": "state", "label": _("State"), "fieldtype": "Data", "width": 110},
		{"fieldname": "applied_invoice", "label": _("Fee Invoice"), "fieldtype": "Link", "options": "Sales Invoice", "width": 140},
		{"fieldname": "discount_amount", "label": _("Discount Given"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "reason", "label": _("Reason"), "fieldtype": "Small Text", "width": 220},
	]  # fmt: skip


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	query = {"company": filters.company}
	if filters.get("academic_year"):
		query["academic_year"] = filters.academic_year
	rows = frappe.get_list("Fee Concession", query, FIELDS, order_by="creation desc", limit=0)
	for row in rows:
		row["concession"] = f"{row.percent}%" if row.concession_type == "Percent" else frappe.format_value(row.amount, "Currency")
		row["state"] = {0: _("Awaiting approval"), 2: _("Cancelled")}.get(row.docstatus) or _(row.status)
	return rows
