"""M17-03 Test-only submittable document that exercises the approval engine in tests."""

from frappe.model.document import Document

from campus.campus_platform.approvals import ApprovableDocument


class ApprovalTestDocument(ApprovableDocument, Document):
	pass
