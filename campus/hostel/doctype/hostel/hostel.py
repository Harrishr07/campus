"""M10-01 Hostel: owned by the trust company and open to one gender; the colleges it serves come from the
Shared Service Agreement (blueprint D4, D8)."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_platform.api import served_companies

SERVICE = "Hostel"


class Hostel(Document):
	def validate(self):
		# only when the hostel is made: a lapsed agreement must not block editing or disabling it
		if self.is_new() and not served_companies(SERVICE, self.company):
			frappe.throw(
				_("{0} has no Hostel Shared Service Agreement as provider in force today").format(
					self.company
				)
			)

	def after_insert(self):
		location = frappe.get_doc(
			{"doctype": "Location", "location_name": f"{self.name} (Hostel)", "is_group": 1}
		).insert(ignore_permissions=True)
		self.db_set("asset_location", location.name)

	def after_delete(self):
		delete_location(self.asset_location)


def delete_location(location):
	if location and frappe.db.exists("Location", location):
		frappe.delete_doc("Location", location, ignore_permissions=True)
