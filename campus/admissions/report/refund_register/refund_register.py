"""M04-04 Refund Register: submitted Admission Cancellations with the refund computed and its documents.

Limited to the companies the user is permitted for.
"""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "name", "label": _("Cancellation"), "fieldtype": "Link", "options": "Admission Cancellation", "width": 150},
		{"fieldname": "cancellation_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 130},
		{"fieldname": "days_since_start", "label": _("Days Since Start"), "fieldtype": "Int", "width": 100},
		{"fieldname": "invoice_total", "label": _("Fee Invoice Total"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "amount_paid", "label": _("Paid"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "deduction", "label": _("Deduction"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "refundable_amount", "label": _("Credit Note Amount"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "cash_refund", "label": _("Cash Refund"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "credit_note", "label": _("Credit Note"), "fieldtype": "Link", "options": "Sales Invoice", "width": 140},
		{"fieldname": "payment_entry", "label": _("Payment Entry"), "fieldtype": "Link", "options": "Payment Entry", "width": 140},
		{"fieldname": "payment_status", "label": _("Payment Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "reason", "label": _("Reason"), "fieldtype": "Data", "width": 220},
	]


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if not filters.company or (permitted is not None and filters.company not in permitted):
		return []
	conditions = [["company", "=", filters.company], ["docstatus", "=", 1]]
	if filters.get("from_date"):
		conditions.append(["cancellation_date", ">=", filters.from_date])
	if filters.get("to_date"):
		conditions.append(["cancellation_date", "<=", filters.to_date])
	rows = frappe.get_list(
		"Admission Cancellation", filters=conditions, order_by="cancellation_date, name", limit=0,
		fields=["name", "cancellation_date", "student", "days_since_start", "invoice_total", "amount_paid", "deduction",
			"refundable_amount", "cash_refund", "credit_note", "payment_entry", "reason"],
	)  # fmt: skip
	for row in rows:
		row["payment_status"] = frappe.db.get_value("Payment Entry", row.payment_entry, "status") if row.payment_entry else None
	return rows
