"""M05-01 Student Onboarding Template: the steps a new student of a company must complete."""

import frappe
from frappe import _
from frappe.model.document import Document


class StudentOnboardingTemplate(Document):
	def validate(self):
		codes = [row.item_code.strip().upper() for row in self.items]
		for row in self.items:
			row.item_code = row.item_code.strip().upper()
		duplicates = {code for code in codes if codes.count(code) > 1}
		if duplicates:
			frappe.throw(_("Item code listed more than once: {0}").format(", ".join(sorted(duplicates))))
		if self.is_default:
			self.check_single_default()

	def check_single_default(self):
		frappe.db.get_value("Company", self.company, "name", for_update=True)  # one default-setter per company at a time
		other = frappe.db.get_value(
			"Student Onboarding Template",
			{"company": self.company, "is_default": 1, "name": ["!=", self.name or ""]},
			for_update=True,  # a locking read sees a default committed while we waited
		)
		if other:
			frappe.throw(_("{0} is already the default template for {1}.").format(other, self.company))
