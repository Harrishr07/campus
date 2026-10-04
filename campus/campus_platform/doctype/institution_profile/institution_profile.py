"""M17-01 Institution Profile: one per Company (autoname = company)."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_platform.api import clear_pack_cache


class InstitutionProfile(Document):
	def validate(self):
		packs = [row.pack for row in self.packs]
		duplicates = {p for p in packs if packs.count(p) > 1}
		if duplicates:
			frappe.throw(_("Pack listed more than once: {0}").format(", ".join(sorted(duplicates))))

	def on_update(self):
		clear_pack_cache()

	def on_trash(self):
		clear_pack_cache()
