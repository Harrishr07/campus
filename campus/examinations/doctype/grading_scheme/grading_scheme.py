"""M12-02, M06-05 Grading Scheme: the grade letters, grade points, mark ranges and result codes of a
regulation, the grading method per course type (absolute, relative Box-Cox above a minimum cohort, online
table), the online-course grade table and the SGPA/CGPA exclusions. Locked once the regulation is Effective."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.examinations.rule_lock import validate_rule_delete, validate_rule_lock
from campus.examinations.rules import ALWAYS_ABSOLUTE, ONLINE, RELATIVE

REQUIRED_CODES = ("U", "SA", "AB")


class GradingScheme(Document):
	def validate(self):
		validate_rule_lock(self)
		validate_ranges(self.grades)
		validate_ranges(self.online_grades)
		if not any(not row.is_pass for row in self.grades):
			frappe.throw(_("A failing grade row (not marked Pass) is required."))
		missing = [code for code in REQUIRED_CODES if code not in {row.code for row in self.codes}]
		if missing:
			frappe.throw(_("Result codes {0} are required.").format(", ".join(missing)))
		self.validate_methods()

	def on_trash(self):
		validate_rule_delete(self)

	def validate_methods(self):
		types = [row.course_type for row in self.methods]
		if len(types) != len(set(types)):
			frappe.throw(_("Each course type may have one grading method."))
		for row in self.methods:
			if row.course_type in ALWAYS_ABSOLUTE and row.method != "Absolute":
				frappe.throw(_("{0} courses are always graded absolutely.").format(_(row.course_type)))
			if row.method == ONLINE and not self.online_grades:
				frappe.throw(
					_("Row {0}: the Online Table method needs online course grades.").format(row.idx)
				)
		if any(row.method == RELATIVE for row in self.methods):
			self.validate_relative_bounds()

	def validate_relative_bounds(self):
		"""Relative bounds fall strictly as the grades fall; the lowest pass grade takes the rest."""
		passes = sorted(
			(row for row in self.grades if row.is_pass), key=lambda row: row.min_mark, reverse=True
		)
		bounds = [row.relative_min_z for row in passes[:-1]]
		if any(high <= low for high, low in zip(bounds, bounds[1:])):
			frappe.throw(_("Relative minimums (SD) must fall from the best pass grade down."))


def validate_ranges(grades):
	ranges = sorted((row.min_mark, row.max_mark, row.letter) for row in grades)
	for low, high, letter in ranges:
		if low > high:
			frappe.throw(_("Grade {0}: the minimum mark exceeds the maximum.").format(letter))
	for (_low, high, first), (low, _high, second) in zip(ranges, ranges[1:]):
		if low <= high:
			frappe.throw(_("Grades {0} and {1} have overlapping mark ranges.").format(first, second))
