"""M12-01 Laboratory: a room of a department of one college with an in-charge, a technician and the courses it serves.
Its equipment is the Assets whose Location is the laboratory's Asset Location."""

import frappe
from frappe import _
from frappe.model.document import Document


class Laboratory(Document):
	def validate(self):
		self.check_same_company()

	def check_same_company(self):
		links = [
			("Department", self.department, "company"),
			("Room", self.room, "oc_company"),
			("Employee", self.in_charge, "company"),
			("Employee", self.technician, "company"),
			*(("Course", row.course, "oc_company") for row in self.courses),
		]
		for doctype, name, field in links:
			if name and frappe.db.get_value(doctype, name, field) != self.company:
				frappe.throw(
					_("{0} {1} does not belong to {2}").format(_(doctype), frappe.bold(name), self.company)
				)

	def after_insert(self):
		location = frappe.get_doc(
			{"doctype": "Location", "location_name": f"{self.name} (Laboratory)"}
		).insert(ignore_permissions=True)
		self.db_set("asset_location", location.name)
