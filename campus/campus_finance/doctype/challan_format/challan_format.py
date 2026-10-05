"""M09-02 Challan Format: a college's bank details, challan and receipt number formats and print template fields."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_finance import numbering


class ChallanFormat(Document):
	def validate(self):
		numbering.validate_prefix(self.challan_prefix)
		numbering.validate_prefix(self.receipt_prefix)
		if min(self.challan_digits, self.receipt_digits) < 1:
			frappe.throw(_("Number digits must be at least 1."))
		account = frappe.db.get_value("Account", self.receiving_account, ["company", "is_group"], as_dict=True)
		if account.company != self.company or account.is_group:
			frappe.throw(_("Receiving Account must be a ledger account of {0}.").format(self.company))
