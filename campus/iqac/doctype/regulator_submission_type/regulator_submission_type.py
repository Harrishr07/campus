"""M01-06 Regulator Submission Type: a return made to a regulator, its due rule and the reminder days (campus.iqac.regulator)."""

import frappe
from frappe import _
from frappe.model.document import Document


class RegulatorSubmissionType(Document):
	def validate(self):
		from campus.iqac import regulator

		regulator.reminder_offsets(self.reminder_days)
		regulator.due_date(self.due_basis, "2000-01-01", self.due_month, self.due_day, self.days_after)
