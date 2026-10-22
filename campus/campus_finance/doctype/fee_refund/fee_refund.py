"""M09-01 Fee Refund: a refund of a paid fee head (or a caution deposit) as a Credit Note and a draft refund Payment Entry.

Needs an approved approval request (Accounts Manager level; the requester and owner cannot approve their own).
Submitting, in one transaction and under the invoice's row lock (campus_finance.fee_refunds): re-checks that the refund
does not exceed what was paid for the head, makes the Credit Note against the invoice, for a Caution Deposit sets the
amount off against the student's dues in the company by a Journal Entry, and drafts the Payment Entry for the cash
that remains (accounts adds the bank reference and submits it). Damages kept from a deposit move to the company's damages income account. Cancelling a Fee Refund cancels
all of that, which frees the amount to be refunded again; it is refused while any submitted payment pays out the credit note.
Admission fees are refunded by Admission Cancellation, not here.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from campus.campus_finance import fee_refunds, refunds
from campus.campus_finance.fee_heads import CAUTION_DEPOSIT

from campus.campus_finance.ledger import head_types
from campus.campus_platform.api import ApprovableDocument, is_approved


class FeeRefund(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		if self.docstatus == 0:
			self.check_invoice()
			self.set_figures(fee_refunds.balance(self.fee_invoice, self.fee_head, self.name or "", locking=False))

	def before_submit(self):
		super().before_submit()
		if not is_approved(self):
			frappe.throw(_("{0} needs approval before it can be submitted. Use Request Approval.").format(self.name))
		self.check_invoice()
		frappe.db.get_value("Sales Invoice", self.fee_invoice, "name", for_update=True)  # lock first, then read again
		self.set_figures(fee_refunds.balance(self.fee_invoice, self.fee_head, self.name, locking=True))
		if flt(self.deduction) > 0 and not frappe.db.get_value("Company", self.company, "oc_damages_income_account"):
			frappe.throw(_("Set the damages income account of {0} to keep damages from a deposit.").format(self.company))
		self.flags.dues = self.settle_dues()

	def on_submit(self):
		invoice = frappe.get_doc("Sales Invoice", self.fee_invoice)
		items = head_items(invoice, self.fee_head)
		note = refunds.make_credit_note(invoice, self.amount, items)
		damages = fee_refunds.make_damages_entry(self, deposit_account(invoice, items)) if flt(self.deduction) > 0 else None
		adjustment = fee_refunds.make_dues_adjustment(self, note, self.flags.dues) if self.flags.dues else None
		payment = self.draft_payment(note) if flt(self.cash_refund) > 0 else None
		self.db_set({"credit_note": note.name, "adjustment_entry": adjustment, "damages_entry": damages, "payment_entry": payment and payment.name})

	def before_cancel(self):
		"""Refused while any payment (its own, an amended one or another Accounts voucher) pays out the credit note:
		cancelling the note would unlink that payment and free the amount to be refunded again."""
		if self.payment_entry:
			frappe.db.get_value("Payment Entry", self.payment_entry, "docstatus", for_update=True)
		paid_by = fee_refunds.paid_by(self.credit_note, exclude=(self.adjustment_entry, self.damages_entry))
		if paid_by:
			frappe.throw(_("The refund was paid out by {0} {1}. If the bank payment was reversed, cancel {0} {1} in Accounts first.").format(*paid_by))

	def on_cancel(self):
		self.ignore_linked_doctypes = ("Sales Invoice", "Payment Entry", "Journal Entry")
		fee_refunds.reverse_vouchers(self)

	def check_invoice(self):
		"""The invoice is a live, non-admission fee invoice of the student, carrying the head; sets the company."""
		invoice = frappe.db.get_value(
			"Sales Invoice", self.fee_invoice, ["docstatus", "is_return", "company", "student", "customer", "oc_program_enrollment"], as_dict=True
		)
		if not invoice or invoice.docstatus != 1 or invoice.is_return:
			frappe.throw(_("{0} is not a submitted fee invoice.").format(self.fee_invoice))
		frappe.has_permission("Sales Invoice", "read", self.fee_invoice, throw=True)
		customer = frappe.db.get_value("Student", self.student, "customer")
		if (invoice.student or None) != self.student and not (not invoice.student and customer and invoice.customer == customer):
			frappe.throw(_("{0} is not an invoice of student {1}.").format(self.fee_invoice, self.student))
		if invoice.oc_program_enrollment:
			frappe.throw(_("{0} is an admission invoice; admission fees are refunded by Admission Cancellation.").format(self.fee_invoice))
		if frappe.db.exists("Admission Cancellation", {"fee_invoice": self.fee_invoice, "docstatus": 1}):
			frappe.throw(_("{0} was refunded by an Admission Cancellation.").format(self.fee_invoice))
		if self.refund_type == CAUTION_DEPOSIT:
			self.fee_head = CAUTION_DEPOSIT
		elif self.fee_head == CAUTION_DEPOSIT:
			frappe.throw(_("A caution deposit is refunded with a Caution Deposit refund."))
		if not fee_refunds.head_share(self.fee_invoice, self.fee_head):
			frappe.throw(_("{0} has no {1} line.").format(self.fee_invoice, self.fee_head))
		refunds.check_uniform_tax(frappe.get_doc("Sales Invoice", self.fee_invoice), head_items(frappe.get_doc("Sales Invoice", self.fee_invoice), self.fee_head))
		self.company = invoice.company

	def set_figures(self, balance):
		"""Fill the figures from the balance and hold the refund to what is available."""
		self.amount_paid, self.already_refunded, self.available = balance.paid, balance.credit_notes + balance.deductions, balance.available
		if self.refund_type == CAUTION_DEPOSIT:
			self.amount = fee_refunds.caution_amount(balance.available, self.deduction)
		else:
			self.deduction = 0
		self.dues_netted, self.cash_refund = 0, flt(self.amount, 2)
		if balance.refunded_before:
			frappe.throw(_("{0} of {1} has already been refunded; a head is refunded once.").format(self.fee_head, self.fee_invoice))
		if flt(balance.outstanding) > fee_refunds.CENT:
			frappe.throw(_("{0} still has {1} unpaid; settle it first, as a credit note would reduce the dues, not return money.").format(self.fee_invoice, balance.outstanding))
		if flt(self.amount) <= 0 or flt(balance.available) <= fee_refunds.CENT:
			frappe.throw(_("There is nothing to refund: {0} is available on {1}.").format(balance.available, self.fee_invoice))
		if flt(self.amount) + flt(self.deduction) > flt(balance.available) + fee_refunds.CENT:
			frappe.throw(_("Only {0} of the {1} paid on {2} is left to refund.").format(balance.available, self.fee_head, self.fee_invoice))

	def settle_dues(self):
		"""For a Caution Deposit: the dues the refund settles; reduces the cash. Run under the invoice lock."""
		if self.refund_type != CAUTION_DEPOSIT:
			return []
		parts = fee_refunds.dues_to_set_off(self.student, self.company, self.fee_invoice, self.amount)
		self.dues_netted = flt(sum(part for _name, part in parts), 2)
		self.cash_refund = flt(flt(self.amount) - self.dues_netted, 2)
		return parts

	def draft_payment(self, note):
		remarks = _("Refund {0} of {1} on {2}: {3}").format(self.name, self.fee_head, self.fee_invoice, self.reason)
		return refunds.make_refund_payment(note, self.cash_refund, self.name, remarks)


def head_items(invoice, head):
	return {row.item_code for row in invoice.items if head_types().get(row.item_code) == head}


def deposit_account(invoice, items):
	"""The liability account the deposit lines of the invoice posted to."""
	return next(row.income_account for row in invoice.items if row.item_code in items)
