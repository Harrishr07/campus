"""M10-01 Hostel Settings: per trust company, the fee heads hostel invoices use."""

import frappe
from frappe import _
from frappe.model.document import Document


class HostelSettings(Document):
	def validate(self):
		self.check_head("hostel_fee_category", "Hostel")
		self.check_head("caution_deposit_category", "Caution Deposit")

	def check_head(self, fieldname, head_type):
		category = self.get(fieldname)
		if frappe.db.get_value("Fee Category", category, "oc_fee_head_type") != head_type:
			frappe.throw(_("{0} must be a Fee Category of head type {1}").format(category, head_type))
