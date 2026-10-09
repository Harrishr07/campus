"""M01-06 Regulator Submission: one return to a regulator with its computed due date, owner, status and documents. Reminders and the
escalation to the Principal run from campus.iqac.regulator."""

import frappe
from frappe import _
from frappe.model.document import Document


class RegulatorSubmission(Document):
	def validate(self):
		from campus.iqac import regulator

		kind = frappe.get_cached_doc("Regulator Submission Type", self.submission_type)
		self.due_date = regulator.due_date(kind.due_basis, self.period_end, kind.due_month, kind.due_day, kind.days_after)
		if self.status in ("Submitted", "Acknowledged") and not self.submitted_on:
			frappe.throw(_("Enter the date the return was submitted."))
