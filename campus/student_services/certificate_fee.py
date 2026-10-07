"""M05-04 Certificate fee: the Sales Invoice raised under the "Certificate" fee category when a certificate is issued.

Same shape as condonation_fee: the issuing user (approver, clerk) may lack the accounts a Sales Invoice posts
to, so the invoice is made in a background job that runs as Administrator (a worker may; the web session is
never touched). Idempotent: a request gets at most one invoice.
"""

import frappe
from frappe import _

from campus.campus_finance.api import raise_fee_invoice

JOB = "campus.student_services.certificate_fee.raise_fee"
FEE_HEAD = "Certificate"


def queue_fee(request):
	if request.fee_amount:
		frappe.enqueue(JOB, queue="short", enqueue_after_commit=True, now=frappe.in_test, request=request.name)


def raise_fee(request):
	"""Worker entry point: raise the invoice of an issued request that has a fee and none yet."""
	caller = frappe.session.user
	frappe.set_user("Administrator")
	try:
		values = frappe.db.get_value(
			"Certificate Request", request, ["docstatus", "fee_amount", "fee_invoice", "student", "company", "certificate_type", "certificate_number"],
			as_dict=True, for_update=True,
		)  # fmt: skip
		if values.docstatus != 1 or not values.fee_amount or values.fee_invoice:
			return
		invoice = raise_fee_invoice(
			values.student, FEE_HEAD, values.fee_amount, values.company,
			_("{0} {1}").format(values.certificate_type, values.certificate_number),
		)  # fmt: skip
		frappe.db.set_value("Certificate Request", request, "fee_invoice", invoice.name)
	finally:
		frappe.set_user(caller)
