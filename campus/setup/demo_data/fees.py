"""PR-03 Fees of the 2026 intake: the selling defaults a fresh site lacks, then the admission invoices paid in full, in
part or not at all. The invoices themselves were raised by Confirm Joining; payments are ordinary Payment Entries made
from them (`get_payment_entry`), so the receivable, the student's fee ledger and the dues check all read real vouchers."""

import frappe
from frappe.utils import flt, getdate

PRICE_LIST = "Standard Selling"
PAID_IN_FULL, PAID_IN_PART = 0.6, 0.1  # of the invoices, by position; the rest stays outstanding


def ensure_selling_defaults():
	"""Confirm Joining raises a Sales Invoice, which needs a selling price list; the ERPNext setup wizard sets it, the pilot kit does not."""
	if not frappe.db.exists("Price List", PRICE_LIST):
		frappe.get_doc({"doctype": "Price List", "price_list_name": PRICE_LIST, "currency": "INR", "selling": 1, "enabled": 1}).insert(ignore_permissions=True)
	if not frappe.db.get_single_value("Selling Settings", "selling_price_list"):
		frappe.db.set_single_value("Selling Settings", "selling_price_list", PRICE_LIST)


def load(ctx):
	"""Pay the open admission invoices of the college: the first 60 percent in full, the next 10 percent half, the rest not at all."""
	invoices = frappe.get_all(
		"Sales Invoice",
		{"company": ctx.college, "docstatus": 1, "is_return": 0, "oc_program_enrollment": ["is", "set"]},
		["name", "student", "grand_total", "outstanding_amount"], order_by="creation, name", limit=0,
	)  # fmt: skip
	for position, invoice in enumerate(invoices):
		share = position / len(invoices)
		if share < PAID_IN_FULL:
			pay(ctx, invoice, invoice.grand_total)
		elif share < PAID_IN_FULL + PAID_IN_PART:
			pay(ctx, invoice, round(invoice.grand_total / 2))


def pay(ctx, invoice, amount):
	"""A submitted Payment Entry of `amount` against the invoice, unless it has been paid (the outstanding is below the amount)."""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	if flt(invoice.outstanding_amount) < flt(amount) or frappe.db.exists("Payment Entry Reference", {"reference_name": invoice.name, "docstatus": 1}):
		return
	payment = get_payment_entry("Sales Invoice", invoice.name, party_amount=amount)
	payment.reference_no, payment.reference_date = f"DEMO-UTR-{invoice.student}", getdate()
	payment.insert(ignore_permissions=True).submit()
	ctx.out.created["Payment Entry"] += 1
