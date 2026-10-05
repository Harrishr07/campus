"""M12-02 Grading Scheme: the grade letters, grade points, mark ranges and result codes of a regulation."""

import frappe
from frappe import _
from frappe.model.document import Document

REQUIRED_CODES = ("U", "SA", "AB")


class GradingScheme(Document):
	def validate(self):
		self.validate_ranges()
		if not any(not row.is_pass for row in self.grades):
			frappe.throw(_("A failing grade row (not marked Pass) is required."))
		missing = [code for code in REQUIRED_CODES if code not in {row.code for row in self.codes}]
		if missing:
			frappe.throw(_("Result codes {0} are required.").format(", ".join(missing)))

	def validate_ranges(self):
		ranges = sorted((row.min_mark, row.max_mark, row.letter) for row in self.grades)
		for low, high, letter in ranges:
			if low > high:
				frappe.throw(_("Grade {0}: the minimum mark exceeds the maximum.").format(letter))
		for (_low, high, first), (low, _high, second) in zip(ranges, ranges[1:]):
			if low <= high:
				frappe.throw(_("Grades {0} and {1} have overlapping mark ranges.").format(first, second))
