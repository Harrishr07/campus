"""M10-01 Hostel Bed: belongs to a room; the room's capacity follows the active beds."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.hostel.doctype.hostel_room.hostel_room import refresh_capacity


class HostelBed(Document):
	def validate(self):
		if not self.room or not frappe.db.exists("Hostel Room", self.room):
			frappe.throw(_("A bed needs a room"))

	def on_update(self):
		refresh_capacity(self.room)

	def after_delete(self):
		refresh_capacity(self.room)
