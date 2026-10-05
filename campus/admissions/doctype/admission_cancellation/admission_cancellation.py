"""M04-04 Admission Cancellation: refund by Refund Rule slab, Credit Note, draft Payment Entry, seat freed.

On submit, in the submit's transaction: a Credit Note against the admission fee invoice for the refundable
portion (invoice total less the slab deduction), a draft Payment Entry (Pay) for the cash actually paid in
excess of the deduction (accounts approves and submits it), cancellation of the Program Enrollment (the Seat
Matrix hook frees the seat), and the student's and applicant's statuses. The applicant becomes "Rejected":
Education's Student Applicant status has no cancelled value and this app does not change upstream options.
A cancellation is final: cancel the Credit Note and Payment Entry in Accounts if it was made in error.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from campus.admissions import refund
from campus.admissions.elevated import system_user


class AdmissionCancellation(Document):
	def validate(self):
		self.validate_enrollment()
		self.compute_refund()

	def validate_enrollment(self):
		enrollment = frappe.db.get_value(
			"Program Enrollment", self.program_enrollment, ["student", "docstatus"], as_dict=True
		)
		if not enrollment or enrollment.docstatus != 1:
			frappe.throw(_("Program Enrollment {0} is not submitted.").format(self.program_enrollment))
		if enrollment.student != self.student:
			frappe.throw(_("Program Enrollment {0} belongs to another student.").format(self.program_enrollment))
		clash = frappe.db.exists(
			"Admission Cancellation", {"program_enrollment": self.program_enrollment, "docstatus": 1, "name": ("!=", self.name)}
		)
		if clash:
			frappe.throw(_("{0} already cancels this admission.").format(clash))

	def compute_refund(self):
		enrollment = frappe.db.get_value(
			"Program Enrollment", self.program_enrollment, ["oc_company", "academic_year"], as_dict=True
		)
		invoice = admission_invoice(self.program_enrollment)
		rule = refund.find_refund_rule(enrollment.oc_company, enrollment.academic_year)
		start = frappe.db.get_value("Academic Year", enrollment.academic_year, "year_start_date")
		days = refund.days_since_start(start, self.cancellation_date)
		result = refund.refund_for(rule.slabs, days, invoice.grand_total)
		paid = flt(invoice.grand_total) - flt(invoice.outstanding_amount)
		self.update(
			{
				"fee_invoice": invoice.name, "refund_rule": rule.name, "admission_start": start, "days_since_start": days,
				"invoice_total": invoice.grand_total, "amount_paid": paid, "deduction": result["deduction"],
				"refundable_amount": result["refundable"], "cash_refund": min(max(paid - result["deduction"], 0), result["refundable"]),
			}
		)  # fmt: skip

	def on_submit(self):
		with system_user():
			credit_note = make_credit_note(self) if self.refundable_amount else None
			payment = make_refund_payment(self, credit_note) if credit_note and self.cash_refund else None
			cancel_enrollment(self.program_enrollment)
		close_records(self)
		self.db_set({"credit_note": credit_note and credit_note.name, "payment_entry": payment and payment.name})

	def before_cancel(self):
		frappe.throw(_("An Admission Cancellation cannot be cancelled; reverse its Credit Note and Payment Entry in Accounts."))


def admission_invoice(program_enrollment):
	name = frappe.db.get_value(
		"Sales Invoice", {"oc_program_enrollment": program_enrollment, "docstatus": 1, "is_return": 0}, "name", order_by="creation desc"
	)
	if not name:
		frappe.throw(_("No submitted fee invoice was raised for Program Enrollment {0}.").format(program_enrollment))
	return frappe.get_doc("Sales Invoice", name)


def make_credit_note(cancellation):
	"""A return against the fee invoice for `refundable_amount`: every line scaled by the same fraction."""
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

	note = make_sales_return(cancellation.fee_invoice)
	note.posting_date = cancellation.cancellation_date
	note.set_posting_time = 1
	note.update_outstanding_for_self = 0
	factor = flt(cancellation.refundable_amount) / flt(cancellation.invoice_total)
	rate_precision = note.items[0].precision("rate")
	for row in note.items:
		row.price_list_rate = row.rate = flt(row.rate * factor, rate_precision)
		row.discount_percentage = 0
	remainder = flt(cancellation.refundable_amount) - sum(-row.qty * row.rate for row in note.items)
	note.items[0].price_list_rate = note.items[0].rate = flt(note.items[0].rate + remainder / -note.items[0].qty, rate_precision)
	note.flags.ignore_permissions = True
	note.insert()
	return note.submit()


def make_refund_payment(cancellation, credit_note):
	"""Draft Payment Entry (Pay) against the credit note, for accounts to review and submit."""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	payment = get_payment_entry("Sales Invoice", credit_note.name, party_amount=-flt(cancellation.cash_refund))
	payment.posting_date = getdate(cancellation.cancellation_date)
	payment.remarks = _("Refund on cancellation of admission {0}: {1}").format(cancellation.name, cancellation.reason)
	payment.reference_no, payment.reference_date = cancellation.name, cancellation.cancellation_date  # accounts replaces with the bank reference
	payment.flags.ignore_permissions = True
	return payment.insert()


def cancel_enrollment(program_enrollment):
	enrollment = frappe.get_doc("Program Enrollment", program_enrollment)
	enrollment.flags.ignore_permissions = True
	enrollment.flags.ignore_links = True  # the cancellation links to the enrollment it cancels
	enrollment.cancel()


def close_records(cancellation):
	"""Student leaves; applicant is closed. Plain writes: Student.validate would put the applicant back to Admitted."""
	frappe.db.set_value(
		"Student", cancellation.student,
		{"enabled": 0, "date_of_leaving": cancellation.cancellation_date, "reason_for_leaving": cancellation.reason},
	)  # fmt: skip
	if cancellation.applicant:
		frappe.db.set_value("Student Applicant", cancellation.applicant, "application_status", "Rejected")
