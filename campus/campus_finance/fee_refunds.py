"""M09-01 Fee Refund rules: how much of a head can still be refunded on an invoice, and the Caution Deposit set-off.

A refund is credited against one fully paid invoice and one fee head (a credit note first reduces what is unpaid, so
a part-paid invoice gives no money back). The most it can be is what the invoice was paid for that head (the
payments received against it, in the ledger's pro-rata head shares) less what has already gone back: every credit note
against the invoice and every damages deduction of an earlier Fee Refund. A head of an invoice is refunded once: ERPNext lets a line be
returned only up to its quantity, so a second credit note on the line is refused (accounts issue any further credit by hand). A Caution Deposit refund is the deposit
less the damages, and the part of it that meets the student's dues in the same company settles those dues
(has_dues `blocking`, the dues a credit elsewhere does not hide) before any cash is paid out.

`balance(..., locking=True)` reads with row locks. Submit takes the invoice's row lock first and then reads with
locking reads, so two refunds on one invoice are serialised and cannot both pass the cap.
"""

import frappe
from frappe import _
from frappe.utils import flt, today

from campus.campus_finance.ledger import has_dues, head_shares
from campus.campus_finance.scholarships import allocate, open_invoices, receivable_of, student_customer


CENT = 0.005


# ---- Rules (no database) -------------------------------------------------------------------


def paid_for_head(receipts, head_share):
	"""What the invoice was paid for the head: the money received against it, in the head's share of the invoice."""
	return flt(flt(receipts) * flt(head_share), 2)


def available_to_refund(paid, credit_notes_total, deductions):
	"""The head's paid amount not yet refunded (credit notes are negative) or deducted."""
	return flt(max(flt(paid) + flt(credit_notes_total) - flt(deductions), 0), 2)


def caution_amount(available, deduction):
	"""The refund of a deposit: what is available less the damages (never negative)."""
	return flt(max(flt(available) - flt(deduction), 0), 2)


def set_off(amount, blocking_dues):
	"""(set against dues, cash) of a deposit refund of `amount` when the student has `blocking_dues`."""
	netted = flt(min(max(flt(blocking_dues), 0), flt(amount)), 2)
	return netted, flt(flt(amount) - netted, 2)


# ---- Facts ---------------------------------------------------------------------------------


def head_share(invoice, head):
	return sum(share for name, share in head_shares([invoice])[invoice] if name == head)


def balance(invoice, head, exclude_refund=None, locking=False):
	"""{paid, credit_notes, deductions, available, outstanding, refunded_before} for `head` on `invoice`; every row read FOR UPDATE when `locking`.

	Money paid is the Payment Entries (Receive) allocated to the invoice: a scholarship waiver or write-off settles
	an invoice but is no money to give back."""
	lock = " for update" if locking else ""
	outstanding = frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount", for_update=locking)
	receipts = frappe.db.sql_list(
		"select ref.allocated_amount from `tabPayment Entry Reference` ref join `tabPayment Entry` pe on pe.name = ref.parent"
		" where ref.reference_doctype = 'Sales Invoice' and ref.reference_name = %s and pe.docstatus = 1 and pe.payment_type = 'Receive'" + lock,
		invoice,
	)
	notes = frappe.db.sql(
		"select name, grand_total from `tabSales Invoice` where return_against = %s and is_return = 1 and docstatus = 1" + lock,
		invoice,
		as_dict=True,
	)
	earlier = frappe.db.sql(
		"select fee_head, deduction from `tabFee Refund` where fee_invoice = %s and fee_head = %s and docstatus = 1 and name != %s" + lock,
		(invoice, head, exclude_refund or ""),
		as_dict=True,
	)
	notes_total, deducted = credited_to_head(notes, head), flt(sum(row.deduction for row in earlier), 2)
	paid = paid_for_head(sum(receipts), head_share(invoice, head))
	return frappe._dict(
		paid=paid, credit_notes=-notes_total, deductions=deducted, outstanding=flt(outstanding, 2),
		refunded_before=bool(earlier),
		available=available_to_refund(paid, notes_total, deducted),
	)


def credited_to_head(notes, head):
	"""The (negative) part of the credit notes `notes` [{name, grand_total}] that falls on `head`, by each note's own lines."""
	shares = head_shares([note.name for note in notes])
	return flt(sum(note.grand_total * sum(share for name, share in shares[note.name] if name == head) for note in notes), 2)


# ---- Settling dues -------------------------------------------------------------------------


def dues_to_set_off(student, company, invoice, amount):
	"""[(invoice, part)] of the student's open invoices in `company` (other than `invoice`) that a refund of `amount` settles.

	Called after the lock is taken: the dues invoices are read under their row locks."""
	blocking = has_dues(student, companies=[company]).blocking
	netted, _cash = set_off(amount, blocking)
	invoices = [(name, due) for name, due in open_invoices(student, company) if name != invoice]
	parts, _left = allocate(netted, invoices)
	return parts


def make_dues_adjustment(refund, credit_note, parts):
	"""Journal Entry moving the credit of the refunded invoice onto the dues in `parts`; returns its name."""
	customer = student_customer(refund.student)
	receivable = receivable_of(customer, refund.company)
	total = flt(sum(part for _name, part in parts), 2)
	entry = frappe.get_doc(
		{
			"doctype": "Journal Entry", "voucher_type": "Journal Entry", "company": refund.company, "posting_date": today(),
			"user_remark": _("Caution deposit refund {0} set against dues").format(refund.name),
			"accounts": [
				{"account": receivable, "party_type": "Customer", "party": customer, "debit_in_account_currency": total,
				 "reference_type": "Sales Invoice", "reference_name": refund.fee_invoice},
				*(
					{"account": receivable, "party_type": "Customer", "party": customer, "credit_in_account_currency": part,
					 "reference_type": "Sales Invoice", "reference_name": name}
					for name, part in parts
				),
			],
		}
	)  # fmt: skip
	entry.flags.ignore_permissions = True
	entry.insert()
	return entry.submit().name


def make_damages_entry(refund, deposit_account):
	"""Journal Entry moving the damages kept from a deposit from its liability account to the company's damages income account."""
	income = frappe.db.get_value("Company", refund.company, "oc_damages_income_account")
	entry = frappe.get_doc(
		{
			"doctype": "Journal Entry", "voucher_type": "Journal Entry", "company": refund.company, "posting_date": today(),
			"user_remark": _("Damages kept from caution deposit refund {0}").format(refund.name),
			"accounts": [
				{"account": deposit_account, "debit_in_account_currency": refund.deduction},
				{"account": income, "credit_in_account_currency": refund.deduction},
			],
		}
	)  # fmt: skip
	entry.flags.ignore_permissions = True
	entry.insert()
	return entry.submit().name


def paid_by(credit_note, exclude=()):
	"""(doctype, name) of a submitted Payment Entry or Journal Entry paying `credit_note` (Journal Entries in `exclude`
	aside), or None. Locks the credit note first, then reads with locking reads."""
	if not credit_note:
		return None
	frappe.db.get_value("Sales Invoice", credit_note, "name", for_update=True)
	payments = frappe.db.sql_list(
		"select pe.name from `tabPayment Entry Reference` ref join `tabPayment Entry` pe on pe.name = ref.parent"
		" where ref.reference_doctype = 'Sales Invoice' and ref.reference_name = %s and pe.docstatus = 1 order by pe.name for update",
		credit_note,
	)
	if payments:
		return "Payment Entry", payments[0]
	entries = frappe.db.sql_list(
		"select je.name from `tabJournal Entry Account` acc join `tabJournal Entry` je on je.name = acc.parent"
		" where acc.reference_type = 'Sales Invoice' and acc.reference_name = %s and je.docstatus = 1 and je.name not in %s"
		" order by je.name for update",
		(credit_note, [name for name in exclude if name] or [""]),
	)
	return ("Journal Entry", entries[0]) if entries else None


def reverse_vouchers(refund):
	"""Cancel what a Fee Refund made, last made first: the payment (deleted while still a draft; a submitted one blocks
	the cancel in before_cancel), the set-off and damages entries, then the credit note. Those Accounts cancelled already stay."""
	if refund.payment_entry:
		if frappe.db.get_value("Payment Entry", refund.payment_entry, "docstatus", for_update=True) == 0:  # a paid one blocks the cancel
			frappe.delete_doc("Payment Entry", refund.payment_entry, force=True, ignore_permissions=True)
			refund.db_set("payment_entry", None)
	for doctype, name in (("Journal Entry", refund.damages_entry), ("Journal Entry", refund.adjustment_entry), ("Sales Invoice", refund.credit_note)):
		if name and frappe.db.get_value(doctype, name, "docstatus") == 1:
			voucher = frappe.get_doc(doctype, name)
			voucher.flags.ignore_permissions = True
			voucher.cancel()


def allow_payment_cancel(doc, method=None):
	"""Doc event (Payment Entry on_cancel): Accounts may cancel a refund payment its Fee Refund still links to;
	the Fee Refund is then cancellable (and not before: see FeeRefund.before_cancel)."""
	if frappe.db.exists("Fee Refund", {"payment_entry": doc.name, "docstatus": 1}):
		doc.ignore_linked_doctypes = (*(doc.get("ignore_linked_doctypes") or ()), "Fee Refund")
