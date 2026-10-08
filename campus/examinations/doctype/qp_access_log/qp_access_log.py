"""M06-03 QP Access Log: one row per attempt to open, list, download, print or withdraw a question paper (allowed
or denied). Append-only: a row is never changed or deleted, by anyone."""

import frappe
from frappe import _
from frappe.model.document import Document


class QPAccessLog(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw(_("QP Access Log rows cannot be changed."))

	def on_trash(self):
		frappe.throw(_("QP Access Log rows cannot be deleted."))
