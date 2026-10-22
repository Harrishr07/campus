"""NFR Mandatory approval: a document type that is never submitted without a matching Approval Policy (rows of
Campus Settings)."""

from frappe.model.document import Document


class ApprovalRequiredDoctype(Document):
	pass
