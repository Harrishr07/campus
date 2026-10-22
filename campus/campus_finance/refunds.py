"""M09-01 Refund builders shared by Admission Cancellation and Fee Refund: what the student paid, the Credit Note and the
draft refund Payment Entry; for an admission cancelled before joining (M04-10), the advance paid and its draft refund.

Both are built here rather than with ERPNext's make_return_doc / get_payment_entry, which check the officer's own
rights on documents (the invoice, Payment Entry) the officer does not hold. Callers resolve every input on the server.
"""

import frappe
from frappe import _
from frappe.utils import flt, today

TAX_FIELDS = ("charge_type", "account_head", "rate", "description", "cost_center", "row_id", "included_in_print_rate")
DISBURSED = "select 1 from `tabScholarship Disbursement` sd where sd.voucher_type = %s and sd.voucher = {0}.name"


def paid_by_student(invoice, locking=False):
	"""The money the student paid on `invoice`: submitted Payment Entries (Receive) allocated to it, except those that
	are scholarship disbursements (a Government scheme's money from the awarding body). Institutional waivers, set-offs,
	write-offs and credit notes are Journal Entries or returns, so they never count. Read FOR UPDATE when `locking`."""
	rows = frappe.db.sql_list(
		"select ref.allocated_amount from `tabPayment Entry Reference` ref join `tabPayment Entry` pe on pe.name = ref.parent"
		" where ref.reference_doctype = 'Sales Invoice' and ref.reference_name = %s and pe.docstatus = 1 and pe.payment_type = 'Receive'"
		f" and not exists ({DISBURSED.format('pe')})" + (" for update" if locking else ""),
		(invoice, "Payment Entry"),
	)
	return flt(sum(rows), 2)


def scholarship_vouchers(invoice, locking=False):
	"""Names of the live scholarship disbursement vouchers (Payment Entries and Journal Entries) that settle `invoice`."""
	lock = " for update" if locking else ""
	payments = frappe.db.sql_list(
		"select distinct pe.name from `tabPayment Entry Reference` ref join `tabPayment Entry` pe on pe.name = ref.parent"
		" where ref.reference_doctype = 'Sales Invoice' and ref.reference_name = %s and pe.docstatus = 1"
		f" and exists ({DISBURSED.format('pe')}){lock}",
		(invoice, "Payment Entry"),
	)
	entries = frappe.db.sql_list(
		"select distinct je.name from `tabJournal Entry Account` acc join `tabJournal Entry` je on je.name = acc.parent"
		" where acc.reference_type = 'Sales Invoice' and acc.reference_name = %s and je.docstatus = 1"
		f" and exists ({DISBURSED.format('je')}){lock}",
		(invoice, "Journal Entry"),
	)
	return sorted(payments + entries)


def make_credit_note(invoice, amount, item_codes=None):
	"""A submitted return against `invoice` (a Sales Invoice document) for `amount`, optionally on the lines of `item_codes` only.

	Every credited line is scaled by the same fraction of its net amount; taxes are copied and recomputed by
	ERPNext, and a last pass moves the first line so the grand total equals `amount` to the paisa. The posting
	date is today, not the original date: it is the GL date, so Accounts' frozen-till date applies as usual.
	"""
	rows = [row for row in invoice.items if item_codes is None or row.item_code in item_codes]
	if not rows:
		frappe.throw(_("{0} has no line to credit.").format(invoice.name))
	check_uniform_tax(invoice, item_codes)
	note = frappe.new_doc("Sales Invoice")
	note.update(
		{
			"company": invoice.company, "customer": invoice.customer, "student": invoice.student, "is_return": 1,
			"return_against": invoice.name, "posting_date": today(), "set_posting_time": 1, "debit_to": invoice.debit_to,
			"selling_price_list": invoice.selling_price_list, "update_outstanding_for_self": 0, "due_date": today(),
			"oc_program_enrollment": invoice.oc_program_enrollment, "currency": invoice.currency,
		}
	)  # fmt: skip
	factor = flt(amount) / credited_gross(invoice, rows)
	for row in rows:
		note.append(
			"items",
			{
				"item_code": row.item_code, "qty": -row.qty, "uom": row.uom, "income_account": row.income_account,
				"cost_center": row.cost_center, "sales_invoice_item": row.name, "rate": flt(row.rate * factor, row.precision("rate")),
			},
		)  # fmt: skip
	for tax in invoice.taxes:
		note.append("taxes", {k: tax.get(k) for k in TAX_FIELDS})
	note.flags.ignore_permissions = True
	note.run_method("set_missing_values")
	note.calculate_taxes_and_totals()
	trim_to_amount(note, flt(amount))
	note.insert()
	return note.submit()


def check_uniform_tax(invoice, item_codes):
	"""A part of the invoice is credited with the invoice's taxes copied, which is right only when every line is taxed alike."""
	if item_codes is None or not invoice.taxes or {row.item_code for row in invoice.items} <= set(item_codes):
		return
	treatments = {(row.item_tax_template, row.item_tax_rate) for row in invoice.items}
	if len(treatments) > 1:
		frappe.throw(_("The invoice has lines with different taxes; credit the whole invoice in Accounts instead."))


def credited_gross(invoice, rows):
	"""What `rows` come to on the invoice including their tax share (the whole grand total when they are all the lines)."""
	if len(rows) == len(invoice.items) or not flt(invoice.net_total):
		return flt(invoice.grand_total)
	return flt(invoice.grand_total) * sum(flt(row.net_amount) for row in rows) / flt(invoice.net_total)


def trim_to_amount(note, amount):
	"""Move the first line so the grand total is exactly -`amount` (rounding of the per-line scaling)."""
	gap = flt(-amount - note.grand_total, 2)
	if not gap:
		return
	first = note.items[0]
	share = flt(note.net_total) / flt(note.grand_total) if note.grand_total else 1
	first.rate = flt(first.rate + gap * share / first.qty, first.precision("rate"))
	note.calculate_taxes_and_totals()


def make_refund_payment(credit_note, amount, reference_no, remarks):
	"""Draft Payment Entry (Pay) of `amount` against `credit_note`, for accounts to review and submit.

	Dated today (GL date). `reference_no` is replaced by accounts with the bank reference.
	"""
	bank = frappe.db.get_value("Company", credit_note.company, "default_bank_account")
	if not bank:
		frappe.throw(_("Set a default bank account for {0} to draft the refund payment.").format(credit_note.company))
	payment = frappe.get_doc(
		{
			"doctype": "Payment Entry", "payment_type": "Pay", "company": credit_note.company, "posting_date": today(),
			"party_type": "Customer", "party": credit_note.customer, "paid_from": bank, "paid_to": credit_note.debit_to,
			"paid_amount": amount, "received_amount": amount, "reference_no": reference_no, "reference_date": today(),
			"remarks": remarks,
			"references": [
				{
					"reference_doctype": "Sales Invoice", "reference_name": credit_note.name,
					"total_amount": credit_note.grand_total, "outstanding_amount": credit_note.outstanding_amount,
					"allocated_amount": -flt(amount),
				}
			],
		}
	)  # fmt: skip
	payment.flags.ignore_permissions = True
	return payment.insert()


def unallocated_advance(customer, company, locking=False):
	"""Money `customer` paid `company` that nothing settles yet: unallocated amounts of submitted Payment Entries
	(Receive) less those of refunds already paid out to them (Pay), never below zero. Scholarship disbursements are
	not the student's money and never count. Read FOR UPDATE when `locking`."""
	rows = frappe.db.sql(
		"select pe.payment_type, sum(pe.unallocated_amount) from `tabPayment Entry` pe"
		" where pe.docstatus = 1 and pe.party_type = 'Customer' and pe.party = %s and pe.company = %s"
		" and pe.payment_type in ('Receive', 'Pay') and pe.unallocated_amount > 0"
		f" and not exists ({DISBURSED.format('pe')}) group by pe.payment_type" + (" for update" if locking else ""),
		(customer, company, "Payment Entry"),
	)
	totals = {payment_type: flt(amount) for payment_type, amount in rows}
	return flt(max(totals.get("Receive", 0) - totals.get("Pay", 0), 0), 2)


def make_advance_refund(customer, company, amount, reference_no, remarks):
	"""Draft Payment Entry (Pay) of `amount` to `customer`, against no invoice: the refund of an advance, for accounts
	to review and submit (and reconcile with the advance). Dated today (GL date)."""
	from erpnext.accounts.party import get_party_account

	bank = frappe.db.get_value("Company", company, "default_bank_account")
	if not bank:
		frappe.throw(_("Set a default bank account for {0} to draft the refund payment.").format(company))
	payment = frappe.get_doc(
		{
			"doctype": "Payment Entry", "payment_type": "Pay", "company": company, "posting_date": today(),
			"party_type": "Customer", "party": customer, "paid_from": bank,
			"paid_to": get_party_account("Customer", customer, company), "paid_amount": amount, "received_amount": amount,
			"reference_no": reference_no, "reference_date": today(), "remarks": remarks,
		}
	)  # fmt: skip
	payment.flags.ignore_permissions = True
	return payment.insert()
