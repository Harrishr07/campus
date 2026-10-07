"""M09-01 One-off fee invoices: a submitted Sales Invoice for a student under one fee head (e.g. Condonation)."""

import frappe
from frappe import _
from frappe.utils import add_days, flt, nowdate

from campus.campus_finance.fee_heads import category_for_type

DUE_DAYS = 15


def raise_fee_invoice(student, head_type, amount, company, remarks):
	"""Create and submit a Sales Invoice of `amount` for `student` under the fee head `head_type`; returns it."""
	customer = frappe.db.get_value("Student", student, "customer")
	if not customer:
		frappe.throw(_("Student {0} has no Customer, so no fee invoice can be raised.").format(frappe.bold(student)))
	if flt(amount) <= 0:
		frappe.throw(_("The fee amount must be positive."))
	today = nowdate()
	invoice = frappe.get_doc(
		{
			"doctype": "Sales Invoice", "company": company, "customer": customer, "student": student,
			"posting_date": today, "set_posting_time": 1, "due_date": add_days(today, DUE_DAYS), "remarks": remarks,
			"items": [{"item_code": category_for_type(head_type), "qty": 1, "rate": amount}],
		}
	)  # fmt: skip
	return post_as_system(invoice)


def post_as_system(invoice):
	"""Insert and submit as Administrator: the caller (e.g. an approver completing an approval) may have no access
	to the receivable and income accounts the invoice posts to, which ERPNext checks for the session user."""
	caller = frappe.session.user
	frappe.set_user("Administrator")
	try:
		invoice.insert(ignore_permissions=True)
		invoice.submit()
	finally:
		frappe.set_user(caller)
	return invoice
