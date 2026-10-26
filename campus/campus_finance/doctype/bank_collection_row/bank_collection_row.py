import frappe
from frappe import _
from frappe.model.document import Document


class BankCollectionRow(Document):
	def on_trash(self):
		"""Deletable only while it has written nothing: refused once the row created a Payment Entry."""
		if self.payment_entry:
			frappe.throw(
				_("Row {0} posted Payment Entry {1}: it is kept as its reference.").format(
					self.row_no, frappe.bold(self.payment_entry)
				)
			)
