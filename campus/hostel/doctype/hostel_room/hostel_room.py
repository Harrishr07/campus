"""M10-01 Hostel Room: capacity is the number of active beds (never typed in), and every room has an Asset Location
for its inventory."""

import frappe
from frappe.model.document import Document


class HostelRoom(Document):
	def validate(self):
		self.capacity = active_bed_count(self.name) if not self.is_new() else 0

	def after_insert(self):
		location = frappe.get_doc(
			{
				"doctype": "Location",
				"location_name": self.name,
				"parent_location": frappe.db.get_value("Hostel", self.hostel, "asset_location"),
			}
		).insert(ignore_permissions=True)
		self.db_set("asset_location", location.name)


def active_bed_count(room):
	return frappe.db.count("Hostel Bed", {"room": room, "is_active": 1})


def refresh_capacity(room):
	"""Set the room's capacity to its active bed count; called when a bed is saved or removed."""
	frappe.db.set_value("Hostel Room", room, "capacity", active_bed_count(room), update_modified=False)
