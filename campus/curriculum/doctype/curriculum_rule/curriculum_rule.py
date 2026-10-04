"""M03-01 Curriculum Rule: the credit-per-period rates and total-credit range of a regulation.

One record per Regulation, so `get_rule(student, "Curriculum Rule")` resolves it.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class CurriculumRule(Document):
	def validate(self):
		if self.max_total_credits and self.min_total_credits > self.max_total_credits:
			frappe.throw(_("Minimum total credits cannot exceed the maximum."))
		if min(self.lecture_credit_per_period, self.tutorial_credit_per_period, self.practical_credit_per_period) < 0:
			frappe.throw(_("Credit per period cannot be negative."))
