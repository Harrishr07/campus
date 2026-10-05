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
from frappe.utils import flt, getdate, today

from campus.admissions import refund
from campus.admissions.admit import check_company_access


class AdmissionCancellation(Document):
	def validate(self):
		self.check_company()
		self.validate_enrollment()
		self.validate_date()
		self.compute_refund()

	def check_company(self):
		"""Before anything is read back to the user: an officer limited to another company gets no figures."""
		company = frappe.db.get_value("Program Enrollment", self.program_enrollment, "oc_company")
		check_company_access(company)

	def validate_date(self):
		"""Cancelled on or after the admission, not in the future (the refund slab counts from this date)."""
		admitted = frappe.db.get_value("Program Enrollment", self.program_enrollment, "enrollment_date")
		if getdate(self.cancellation_date) > getdate(today()):
			frappe.throw(_("The cancellation date cannot be in the future."))
		if admitted and getdate(self.cancellation_date) < getdate(admitted):
			frappe.throw(_("The cancellation date cannot be before the admission date {0}.").format(admitted))

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
	"""A return against the fee invoice for `refundable_amount`, built here rather than with ERPNext's
	make_return_doc (which needs read rights on the invoice the officer does not hold).

	Every line is scaled by the same fraction of the net amount; taxes are copied and recomputed by ERPNext, and
	a last pass moves the first line so the grand total equals the refundable amount to the paisa. The posting
	date is today, not the cancellation date: it is the GL date, so Accounts' frozen-till date applies as usual.
	"""
	invoice = frappe.get_doc("Sales Invoice", cancellation.fee_invoice)
	note = frappe.new_doc("Sales Invoice")
	note.update(
		{
			"company": invoice.company, "customer": invoice.customer, "student": invoice.student, "is_return": 1,
			"return_against": invoice.name, "posting_date": today(), "set_posting_time": 1, "debit_to": invoice.debit_to,
			"selling_price_list": invoice.selling_price_list, "update_outstanding_for_self": 0, "due_date": today(),
			"oc_program_enrollment": invoice.oc_program_enrollment, "currency": invoice.currency,
		}
	)  # fmt: skip
	factor = flt(cancellation.refundable_amount) / flt(invoice.grand_total)
	for row in invoice.items:
		note.append(
			"items",
			{
				"item_code": row.item_code, "qty": -row.qty, "uom": row.uom, "income_account": row.income_account,
				"cost_center": row.cost_center, "sales_invoice_item": row.name, "rate": flt(row.rate * factor, row.precision("rate")),
			},
		)  # fmt: skip
	for tax in invoice.taxes:
		note.append(
			"taxes",
			{k: tax.get(k) for k in ("charge_type", "account_head", "rate", "description", "cost_center", "row_id", "included_in_print_rate")},
		)
	note.flags.ignore_permissions = True
	note.run_method("set_missing_values")
	note.calculate_taxes_and_totals()
	trim_to_refundable(note, flt(cancellation.refundable_amount))
	note.insert()
	return note.submit()


def trim_to_refundable(note, refundable):
	"""Move the first line so the grand total is exactly -`refundable` (rounding of the per-line scaling)."""
	gap = flt(-refundable - note.grand_total, 2)
	if not gap:
		return
	first = note.items[0]
	share = flt(note.net_total) / flt(note.grand_total) if note.grand_total else 1
	first.rate = flt(first.rate + gap * share / first.qty, first.precision("rate"))
	note.calculate_taxes_and_totals()


def make_refund_payment(cancellation, credit_note):
	"""Draft Payment Entry (Pay) against the credit note, for accounts to review and submit.

	Dated today (GL date); the cancellation date is in the remarks. Built here: ERPNext's get_payment_entry
	checks the officer's own Payment Entry rights.
	"""
	bank = frappe.db.get_value("Company", credit_note.company, "default_bank_account")
	if not bank:
		frappe.throw(_("Set a default bank account for {0} to draft the refund payment.").format(credit_note.company))
	payment = frappe.get_doc(
		{
			"doctype": "Payment Entry", "payment_type": "Pay", "company": credit_note.company, "posting_date": today(),
			"party_type": "Customer", "party": credit_note.customer, "paid_from": bank, "paid_to": credit_note.debit_to,
			"paid_amount": cancellation.cash_refund, "received_amount": cancellation.cash_refund,
			"reference_no": cancellation.name, "reference_date": today(),  # accounts replaces with the bank reference
			"remarks": _("Refund on cancellation of admission {0} dated {1}: {2}").format(
				cancellation.name, cancellation.cancellation_date, cancellation.reason
			),
			"references": [
				{
					"reference_doctype": "Sales Invoice", "reference_name": credit_note.name,
					"total_amount": credit_note.grand_total, "outstanding_amount": credit_note.outstanding_amount,
					"allocated_amount": -flt(cancellation.cash_refund),
				}
			],
		}
	)  # fmt: skip
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
