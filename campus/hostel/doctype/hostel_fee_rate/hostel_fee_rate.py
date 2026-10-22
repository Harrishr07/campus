"""M10-01 Hostel Fee Rate: fee category amounts of a room type for an academic year, per owning company."""

import frappe
from frappe import _
from frappe.model.document import Document


class HostelFeeRate(Document):
	def validate(self):
		categories = [row.fee_category for row in self.items]
		if len(categories) != len(set(categories)):
			frappe.throw(_("A fee category is listed more than once"))
		for row in self.items:
			if row.amount < 0:
				frappe.throw(_("Row {0}: amount cannot be negative").format(row.idx))
