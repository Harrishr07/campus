"""M05-03 Classification Rule: the classes (distinction, first, second …) a regulation awards on its CGPA,
first-appearance, duration and break-of-study conditions, with Honours / Minor variants.
Evaluated by campus.examinations.rules.classify in row order."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.examinations.rule_lock import validate_rule_delete, validate_rule_lock


class ClassificationRule(Document):
	def validate(self):
		validate_rule_lock(self)
		for row in self.classes:
			if not 0 <= row.cgpa_min <= 10:
				frappe.throw(_("Row {0}: the CGPA minimum lies within 0-10.").format(row.idx))

	def on_trash(self):
		validate_rule_delete(self)
