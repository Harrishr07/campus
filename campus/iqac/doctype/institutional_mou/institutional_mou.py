"""M01-07 Institutional MoU: a partner, purpose, period and the activities held under it; read by AQAR 3.7.2, placement and research."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today


class InstitutionalMoU(Document):
	def validate(self):
		if getdate(self.valid_to) < getdate(self.valid_from):
			frappe.throw(_("Valid To cannot be before Valid From."))
		for row in self.activities:
			if not getdate(self.valid_from) <= getdate(row.activity_date) <= getdate(self.valid_to):
				frappe.throw(_("Row {0}: the activity date is outside the period of the MoU.").format(row.idx))
		self.status = mou_status(self.valid_from, self.valid_to, self.terminated)


def mou_status(valid_from, valid_to, terminated, on_date=None):
	on_date = getdate(on_date or today())
	if terminated:
		return "Terminated"
	if on_date < getdate(valid_from):
		return "Upcoming"
	return "Expired" if on_date > getdate(valid_to) else "Active"
