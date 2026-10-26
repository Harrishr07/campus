"""M06-04 Remuneration Register: examiner remuneration claims of a college (draft and submitted), with the payment
each made (Additional Salary or Purchase Invoice) and, for external examiners, TDS and net payable.

Limited to the companies the user is permitted for and to the claims the user may read."""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies

FIELDS = [
	"name", "posting_date", "exam_session", "examiner_type", "examiner_name", "employee", "external_member",
	"total_amount", "additional_salary", "payroll_date", "purchase_invoice", "tds_amount", "net_payable", "docstatus",
]  # fmt: skip
STATUS = {0: "Draft", 1: "Submitted"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "claim", "label": _("Claim"), "fieldtype": "Link", "options": "Examiner Remuneration Claim", "width": 150},
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "exam_session", "label": _("Exam Session"), "fieldtype": "Link", "options": "Exam Session", "width": 120},
		{"fieldname": "examiner_type", "label": _("Type"), "fieldtype": "Data", "width": 80},
		{"fieldname": "examiner_name", "label": _("Examiner"), "fieldtype": "Data", "width": 160},
		{"fieldname": "total_amount", "label": _("Amount"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "tds_amount", "label": _("TDS"), "fieldtype": "Currency", "width": 90},
		{"fieldname": "net_payable", "label": _("Net Payable"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "additional_salary", "label": _("Additional Salary"), "fieldtype": "Link", "options": "Additional Salary", "width": 150},
		{"fieldname": "payroll_date", "label": _("Payroll Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "purchase_invoice", "label": _("Purchase Invoice"), "fieldtype": "Link", "options": "Purchase Invoice", "width": 150},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 90},
	]  # fmt: skip


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	conditions = {"company": filters.company, "docstatus": ["<", 2]}
	for field in ("exam_session", "examiner_type"):
		if filters.get(field):
			conditions[field] = filters[field]
	if filters.from_date and filters.to_date:
		conditions["posting_date"] = ["between", [filters.from_date, filters.to_date]]
	elif filters.from_date or filters.to_date:
		conditions["posting_date"] = (
			[">=", filters.from_date] if filters.from_date else ["<=", filters.to_date]
		)
	rows = frappe.get_list(
		"Examiner Remuneration Claim", filters=conditions, fields=FIELDS, order_by="posting_date, name"
	)
	for row in rows:
		row.claim = row.pop("name")
		row.status = _(STATUS[row.pop("docstatus")])
		if row.examiner_type == "Internal":
			row.net_payable = row.total_amount
	return rows
