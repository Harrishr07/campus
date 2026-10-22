"""M10-01 Hostel Room: capacity is the number of active beds (owned by bed events, never typed in), and every room
has an Asset Location for its inventory."""

import frappe
from frappe.model.document import Document

from campus.hostel.doctype.hostel.hostel import delete_location


class HostelRoom(Document):
	def validate(self):
		# capacity belongs to bed events: keep the committed value, read under the row lock so a save never
		# overwrites a concurrent bed commit with a stale count
		self.capacity = 0 if self.is_new() else lock_room(self.name).capacity

	def after_insert(self):
		location = frappe.get_doc(
			{
				"doctype": "Location",
				"location_name": self.name,
				"parent_location": frappe.db.get_value("Hostel", self.hostel, "asset_location"),
			}
		).insert(ignore_permissions=True)
		self.db_set("asset_location", location.name)

	def after_delete(self):
		delete_location(self.asset_location)


def lock_room(room):
	"""The room's row, locked until the end of the transaction."""
	return frappe.db.get_value("Hostel Room", room, ["capacity"], as_dict=True, for_update=True)


def refresh_capacity(room):
	"""Set the room's capacity to its active bed count; called when a bed is saved or removed.

	The room row is locked first and the beds counted with a locking read, so concurrent bed changes
	of one room queue up and the last one writes the true count."""
	lock_room(room)
	count = frappe.db.sql("select count(*) from `tabHostel Bed` where room = %s and is_active = 1 for update", room)[0][0]
	frappe.db.set_value("Hostel Room", room, "capacity", count, update_modified=False)
