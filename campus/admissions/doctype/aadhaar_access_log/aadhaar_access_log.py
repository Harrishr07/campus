"""M04-02 Aadhaar Access Log: one immutable row per reveal of a full Aadhaar number (decision D12).

Frappe's own Access Log is purged after 30 days and written through a deferred queue, so reveals are
logged here instead: each row is written on a separate database connection and committed at once
(`campus.admissions.aadhaar.write_on_own_connection`), so it survives a rollback of the reveal's transaction,
and is never purged.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class AadhaarAccessLog(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw(_("Aadhaar Access Log rows cannot be edited."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("Aadhaar Access Log rows cannot be deleted."), frappe.PermissionError)
