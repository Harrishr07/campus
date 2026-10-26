"""M16 Message Log."""

from frappe.model.document import Document

from campus.campus_messaging.scope import company_of


class MessageLog(Document):
	def before_insert(self):
		"""Company of the record the message is about, else of the recipient (for company-scoped reports)."""
		if self.company:
			return
		party_type, _sep, party = (self.recipient or "").partition(":")
		self.company = company_of(self.reference_doctype, self.reference_name) or company_of(
			party_type, party
		)
