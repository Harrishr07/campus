"""M05-02 Condonation fee: the Sales Invoice raised after a Condonation Request is approved.

The approval completes in an approver's web request, and an approver (HOD, Dean) usually has no access to
the accounts a Sales Invoice posts to, which ERPNext checks for the session user. So the invoice is made in a
background job (queued after the approval commits) that runs as Administrator, which is what a worker may do
(the web session is never touched). The job is idempotent: a request gets at most one invoice.
"""

import frappe
from frappe import _

from campus.campus_finance.api import raise_fee_invoice

JOB = "campus.student_services.condonation_fee.raise_fee"
FEE_HEAD = "Condonation"


def queue_fee(request):
	"""Queue the fee invoice of a submitted request (inline under tests, like the messaging dispatch)."""
	if request.fee_amount:
		frappe.enqueue(
			JOB, queue="short", enqueue_after_commit=True, now=frappe.in_test, request=request.name
		)


def raise_fee(request):
	"""Worker entry point: raise the invoice of an approved request that has a fee and none yet."""
	caller = frappe.session.user
	frappe.set_user("Administrator")
	try:
		values = frappe.db.get_value(
			"Condonation Request", request, ["docstatus", "fee_amount", "fee_invoice", "student", "company", "academic_term"],
			as_dict=True, for_update=True,
		)  # fmt: skip
		if values.docstatus != 1 or not values.fee_amount or values.fee_invoice:
			return
		invoice = raise_fee_invoice(
			values.student, FEE_HEAD, values.fee_amount, values.company,
			_("Condonation of attendance shortage, {0}").format(values.academic_term),
		)  # fmt: skip
		frappe.db.set_value("Condonation Request", request, "fee_invoice", invoice.name)
	finally:
		frappe.set_user(caller)
