"""M09-02 Bank Collection Import: a bank's CSV of collections, matched to challans and posted as Payment Entries."""

import frappe
from frappe import _
from frappe.model.document import Document


class BankCollectionImport(Document):
	def on_trash(self):
		"""Deletable only while it has written nothing: refused once it has started or a row created a Payment Entry."""
		if self.status != "Draft" or frappe.db.exists(
			"Bank Collection Row", {"bank_collection_import": self.name, "payment_entry": ["is", "set"]}
		):
			frappe.throw(
				_("{0} has been processed: it is kept as the reference of the payments it posted.").format(
					frappe.bold(self.name)
				)
			)
