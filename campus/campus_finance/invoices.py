"""M09-01 One-off fee invoices: a submitted Sales Invoice for a student under one fee head (e.g. Condonation); opening entries."""

import frappe
from frappe import _
from frappe.utils import add_days, flt, nowdate

from campus.campus_finance.fee_heads import category_for_type

DUE_DAYS = 15


def is_opening(doc):
	"""Whether `doc` is an opening entry (a balance brought forward), whatever the case of its is_opening value."""
	return (doc.get("is_opening") or "").strip().casefold() == "yes"


def raise_fee_invoice(student, head_type, amount, company, remarks):
	"""Create and submit a Sales Invoice of `amount` for `student` under the fee head `head_type`; returns it."""
	customer = frappe.db.get_value("Student", student, "customer")
	if not customer:
		frappe.throw(_("Student {0} has no Customer, so no fee invoice can be raised.").format(frappe.bold(student)))
	if flt(amount) <= 0:
		frappe.throw(_("The fee amount must be positive."))
	receivable = frappe.db.get_value("Company", company, "default_receivable_account")
	if not receivable:
		frappe.throw(_("Company {0} has no default receivable account.").format(frappe.bold(company)))
	today = nowdate()
	invoice = frappe.get_doc(
		{
			"doctype": "Sales Invoice", "company": company, "customer": customer, "student": student,
			"posting_date": today, "set_posting_time": 1, "due_date": add_days(today, DUE_DAYS), "remarks": remarks,
			"debit_to": receivable,
			"items": [{"item_code": category_for_type(head_type), "qty": 1, "rate": amount}],
		}
	)  # fmt: skip
	invoice.flags.ignore_permissions = True  # the caller (e.g. an approver) may lack Accounts rights; every input is server-side
	invoice.insert()
	return invoice.submit()
