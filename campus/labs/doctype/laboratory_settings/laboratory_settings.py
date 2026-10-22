"""M12-05 Laboratory Settings: the days ahead calibration notices start."""

import frappe
from frappe import _
from frappe.model.document import Document


class LaboratorySettings(Document):
	def validate(self):
		if int(self.calibration_notice_days) < 0:
			frappe.throw(_("Notice days cannot be negative."))
