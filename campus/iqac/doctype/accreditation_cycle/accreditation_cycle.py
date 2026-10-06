"""M15-01 Accreditation Cycle: one framework for one college (Company) and academic year; Metric Values hang off it."""

import frappe
from frappe import _
from frappe.model.document import Document


class AccreditationCycle(Document):
	def validate(self):
		if frappe.db.exists(
			"Accreditation Cycle",
			{
				"framework": self.framework, "company": self.company, "academic_year": self.academic_year,
				"name": ["!=", self.name],
			},
		):  # fmt: skip
			frappe.throw(_("{0} already has a cycle of {1} for {2}.").format(self.company, self.framework, self.academic_year))
