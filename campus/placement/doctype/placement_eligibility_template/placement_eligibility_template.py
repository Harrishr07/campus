"""M14-01 Placement Eligibility Template: criteria a drive starts from."""

import frappe
from frappe import _
from frappe.model.document import Document


class PlacementEligibilityTemplate(Document):
	def validate(self):
		if frappe.utils.flt(self.min_cgpa) < 0:
			frappe.throw(_("The minimum CGPA cannot be negative"))
		if frappe.utils.cint(self.max_standing_arrears) < 0:
			frappe.throw(_("Standing arrears allowed cannot be negative"))
