"""M17-01 Module Pack: a switchable group of features with allowed institution statuses."""

from frappe.model.document import Document

from campus.campus_platform.api import clear_pack_cache


class ModulePack(Document):
	def validate(self):
		self.code = self.code.strip().upper()

	def on_update(self):
		clear_pack_cache()

	def on_trash(self):
		clear_pack_cache()
