"""M06-01 Exam fee: the fee of a confirmed Exam Registration, its Sales Invoice, and the exam dues gate.

The fee is the Exam Fee Rate's fee per eligible course plus the late fee slab of the days after the session's
registration closing date (registration_rules.late_fee); both are records, never constants.

The student confirms in a portal request, and a student has no access to the accounts a Sales Invoice posts to,
which ERPNext checks for the session user. So the invoice is made in a background job queued after the
confirmation commits, running as Administrator as a worker may (the web session is never touched), as the
condonation fee does. The job is idempotent: a registration gets at most one invoice. Confirmation checks the
invoice can be raised (Customer, receivable account, Exam fee head) before fixing the fee; should the job still
fail, the COE re-raises the missing invoices of a session (reraise_invoices, a bulk run of the same job).

Exam dues (fee head type Exam) never block registration; exam_dues_block is the gate for hall tickets.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, today

from campus.campus_finance.api import check_fee_invoice, has_dues, raise_fee_invoice
from campus.campus_platform.bulk import run_bulk
from campus.examinations.access import COE_ROLE
from campus.examinations.registration_rules import late_fee

JOB = "campus.examinations.exam_fee.raise_fee"
EXAM_HEAD = "Exam"
RATE, DOCTYPE = "Exam Fee Rate", "Exam Registration"
RERAISE_RUN = "Exam Fee Invoice"
RERAISE_HANDLER = "campus.examinations.exam_fee.reraise_fee_item"


def fee_rate(company, program):
	"""The Exam Fee Rate of the program in the company, else the company's blank-program rate."""
	candidates = ([{"company": company, "program": program}] if program else []) + [
		{"company": company, "program": ["is", "not set"]}
	]
	for filters in candidates:
		name = frappe.db.get_value(RATE, filters)
		if name:
			return frappe.get_doc(RATE, name)
	frappe.throw(_("No Exam Fee Rate is set for {0}.").format(frappe.bold(company)))


def registration_fee(company, program, eligible_courses, registration_closes):
	"""{late_days, exam_fee, late_fee, fee_total} of a registration confirmed today. Refused past the last slab."""
	rate = fee_rate(company, program)
	days = max(date_diff(today(), registration_closes), 0) if registration_closes else 0
	late = late_fee(days, [(s.from_day, s.to_day, flt(s.late_fee)) for s in rate.late_fee_slabs])
	if late is None:
		frappe.throw(_("Registration for this session closed {0} days ago.").format(days))
	exam = flt(rate.fee_per_course) * eligible_courses
	return {"late_days": days, "exam_fee": exam, "late_fee": late, "fee_total": exam + late}


def check_invoiceable(student, company):
	"""Throw unless the exam fee invoice of `student` in `company` can be raised (checked before confirming)."""
	check_fee_invoice(student, EXAM_HEAD, company)


def queue_fee(registration):
	"""Queue the fee invoice of a confirmed registration (inline under tests, like the condonation fee)."""
	if flt(registration.fee_total) > 0:
		frappe.enqueue(
			JOB, queue="short", enqueue_after_commit=True, now=frappe.in_test, registration=registration.name
		)


def raise_fee(registration):
	"""Worker entry point: raise the invoice of a confirmed registration that has a fee and none yet."""
	caller = frappe.session.user
	frappe.set_user("Administrator")
	try:
		values = frappe.db.get_value(
			DOCTYPE, registration, ["confirmed", "fee_total", "fee_invoice", "student", "company", "exam_session"],
			as_dict=True, for_update=True,
		)  # fmt: skip
		if not values.confirmed or flt(values.fee_total) <= 0 or values.fee_invoice:
			return
		invoice = raise_fee_invoice(
			values.student,
			EXAM_HEAD,
			values.fee_total,
			values.company,
			_("Exam fee, {0}").format(values.exam_session),
		)
		frappe.db.set_value(DOCTYPE, registration, "fee_invoice", invoice.name)
	finally:
		frappe.set_user(caller)


def reraise_invoices(exam_session):
	"""Queue the invoice job for the session's confirmed registrations that have a fee and no invoice (COE only).

	Returns the Bulk Run name, or None when none is missing. Idempotent: raise_fee skips an invoiced registration.
	"""
	frappe.only_for((COE_ROLE, "System Manager"))
	frappe.get_doc("Exam Session", exam_session).check_permission("write")
	names = frappe.get_all(
		DOCTYPE,
		{"exam_session": exam_session, "confirmed": 1, "fee_total": [">", 0], "fee_invoice": ["is", "not set"]},
		pluck="name", order_by="name",
	)  # fmt: skip
	if not names:
		frappe.msgprint(
			_("Every confirmed registration of {0} has its exam fee invoice.").format(
				frappe.bold(exam_session)
			)
		)
		return None
	return run_bulk(RERAISE_RUN, names, RERAISE_HANDLER)


def reraise_fee_item(registration, run):
	"""Bulk handler of reraise_invoices: raise one registration's missing invoice (in the worker, no commit)."""
	raise_fee(registration)


def exam_dues_block(student, exam_session):
	"""{blocked, amount}: whether the student's unpaid Exam-head dues in the session's company block a hall ticket."""
	company = frappe.db.get_value("Exam Session", exam_session, "company")
	dues = has_dues(student, scopes=[EXAM_HEAD], companies=[company])
	return frappe._dict(blocked=dues.blocking > 0, amount=dues.blocking)
