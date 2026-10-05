"""M04-02 Eligibility Rule: qualifying exam, required subjects and minimum marks % per category for a program."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class EligibilityRule(Document):
	def validate(self):
		seen = set()
		for row in self.category_marks:
			if row.student_category in seen:
				frappe.throw(_("Row {0}: category {1} is repeated.").format(row.idx, row.student_category))
			seen.add(row.student_category)
			if not 0 <= flt(row.min_percent) <= 100:
				frappe.throw(_("Row {0}: minimum marks must be between 0 and 100.").format(row.idx))
		self.validate_single_enabled_rule()

	def validate_single_enabled_rule(self):
		if not self.enabled:
			return
		clash = frappe.db.exists(
			"Eligibility Rule",
			{"program": self.program, "regulation": self.regulation or ["is", "not set"], "enabled": 1, "name": ["!=", self.name]},
		)
		if clash:
			frappe.throw(_("Eligibility Rule {0} already covers this program and regulation.").format(clash))
