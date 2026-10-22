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
		if self.owner_employee and frappe.db.get_value("Employee", self.owner_employee, "company") != self.company:
			frappe.throw(_("The owner must be an employee of {0}.").format(frappe.bold(self.company)))
		if self.status in ("Submitted", "Acknowledged") and not self.submitted_on:
			frappe.throw(_("Enter the date the return was submitted."))
