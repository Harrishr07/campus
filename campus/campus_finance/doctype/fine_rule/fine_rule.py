"""M09-01 Fine Rule: grace days and slabs deciding the late fee on an overdue fee invoice."""

from frappe.model.document import Document

from campus.campus_finance import fines


class FineRule(Document):
	def validate(self):
		fines.validate_rule(self)
