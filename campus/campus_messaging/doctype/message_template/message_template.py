"""M16-01 Message Template: one event key, its channels and per-language bodies."""

import frappe
from frappe import _
from frappe.model.document import Document


class MessageTemplate(Document):
	def validate(self):
		channels = [row.channel for row in self.channels]
		if len(set(channels)) != len(channels):
			frappe.throw(_("Each channel can be listed only once."))
		languages = [row.language for row in self.bodies]
		if "en" not in languages:
			frappe.throw(_("An English (en) body is required as the fallback language."))
		if len(set(languages)) != len(languages):
			frappe.throw(_("Each language can have only one body."))
