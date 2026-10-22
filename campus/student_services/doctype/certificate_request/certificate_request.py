"""M05-04 Certificate Request: a student asks for a certificate; on issue it becomes a Verifiable Document.

The request is made in the portal (student_services.portal.request_certificate) or on the desk. If the type
needs approval the request is approved through the generic approval engine (an Approval Policy for this
doctype must exist; without one a needs-approval type cannot be issued); approval submits it. Submitting
is issuing: the certificate number is allotted (per type, company and year), the Verifiable Document with
its QR is created and, for a Transfer Certificate, the Student's leaving fields and academic status are set,
all in the one transaction. A fee, if any, is invoiced afterwards in a background job.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission
from frappe.utils import now_datetime

from campus.campus_platform import verification
from campus.campus_platform.api import ApprovableDocument, is_approved
from campus.student_services import certificates
from campus.student_services.certificate_fee import queue_fee


class CertificateRequest(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.set_company()
		if self.docstatus == 0:
			self.apply_type()
			self.check_open_request()
			if self.is_transfer_certificate:
				self.check_transfer()

	def before_submit(self):
		super().before_submit()
		if self.needs_approval and not is_approved(self):
			frappe.throw(_("{0} needs approval before it can be issued. Use Request Approval.").format(self.name))
		if self.is_transfer_certificate:
			certificates.check_transfer_allowed(self.student)
		self.certificate_number = certificates.next_certificate_number(self.certificate_type, self.company)
		self.issued_on = now_datetime()

	def on_submit(self):
		type_values = frappe.db.get_value("Certificate Type", self.certificate_type, ["verifiable", "print_format"], as_dict=True)
		if type_values.verifiable:
			self.db_set("verification_code", verification.issue(self, type_values.print_format).code)
		if self.is_transfer_certificate:
			certificates.apply_leaving(self)
		queue_fee(self)

	def before_cancel(self):
		if self.fee_invoice and frappe.db.get_value("Sales Invoice", self.fee_invoice, "docstatus") == 1:
			frappe.throw(_("Cancel or credit the fee invoice {0} before cancelling this certificate.").format(self.fee_invoice))

	def on_cancel(self):
		verification.revoke_for(self, _("Certificate {0} was cancelled.").format(self.certificate_number))
		if self.is_transfer_certificate:
			certificates.undo_leaving(self)

	def set_company(self):
		student = frappe.get_doc("Student", self.student)
		if not has_user_permission(student):  # Company User Permissions
			frappe.throw(_("You are not permitted to request a certificate for {0}.").format(frappe.bold(self.student)), frappe.PermissionError)
		self.company = student.oc_company

	def apply_type(self):
		"""Needs-approval, fee and TC flag come from the type, never from the request."""
		kind = frappe.get_doc("Certificate Type", self.certificate_type)
		if not kind.enabled:
			frappe.throw(_("Certificate type {0} is not available.").format(frappe.bold(kind.name)))
		self.needs_approval = kind.needs_approval
		self.fee_amount = kind.fee_amount
		self.is_transfer_certificate = kind.is_transfer_certificate
		if not kind.is_transfer_certificate:
			self.leaving_date = self.reason_for_leaving = None

	def check_open_request(self):
		if frappe.db.exists(
			"Certificate Request",
			{"student": self.student, "certificate_type": self.certificate_type, "docstatus": 0, "name": ["!=", self.name]},
		):
			frappe.throw(_("{0} already has an open {1} request.").format(frappe.bold(self.student), self.certificate_type))

	def check_transfer(self):
		if not (self.reason_for_leaving or "").strip():
			frappe.throw(_("Give the reason for leaving for a transfer certificate."))
		certificates.check_transfer_allowed(self.student)
