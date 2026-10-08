"""M06-03 Question Paper Settings: the download lead time and the slot times (records, not constants)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class QuestionPaperSettings(Document):
	def validate(self):
		if cint(self.download_lead_minutes) < 0 or cint(self.slot_minutes) <= 0:
			frappe.throw(_("The lead time cannot be negative and the slot must last at least a minute."))
