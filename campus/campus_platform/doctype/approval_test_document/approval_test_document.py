"""M17-03 Test-only submittable document that exercises the approval engine in tests."""

import frappe
from frappe.model.document import Document

from campus.campus_platform.approvals import ApprovableDocument


class ApprovalTestDocument(ApprovableDocument, Document):
	def before_approval_request(self):
		if self.notes == "refuse-request":
			frappe.throw("Refused before the request.")
