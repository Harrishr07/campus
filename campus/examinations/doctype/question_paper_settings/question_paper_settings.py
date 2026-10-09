"""M06-03 Question Paper Settings: the download lead time and the slot times (records, not constants). The lead is
at most MAX_LEAD_MINUTES: a longer lead would open sealed papers long before their exam."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

MAX_LEAD_MINUTES = 120


class QuestionPaperSettings(Document):
	def validate(self):
		if not 0 <= cint(self.download_lead_minutes) <= MAX_LEAD_MINUTES:
			frappe.throw(_("The download lead must be between 0 and {0} minutes.").format(MAX_LEAD_MINUTES))
		if cint(self.slot_minutes) <= 0:
			frappe.throw(_("The slot must last at least a minute."))
