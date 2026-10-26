"""M04-05 Enquiry Follow-up Rule: days after an enquiry at which the assigned officer gets a reminder ToDo."""

import frappe
from frappe import _
from frappe.model.document import Document


class EnquiryFollowupRule(Document):
	def validate(self):
		if self.days_after < 1:
			frappe.throw(_("Days After Enquiry must be at least 1."))
		duplicate = frappe.db.exists(
			"Enquiry Follow-up Rule",
			{"company": self.company, "days_after": self.days_after, "name": ("!=", self.name)},
		)
		if duplicate:
			frappe.throw(
				_("{0} already has a follow-up rule for day {1}.").format(self.company, self.days_after)
			)
