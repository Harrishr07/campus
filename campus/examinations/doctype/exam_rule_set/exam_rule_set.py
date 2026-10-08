"""M12-02, M06-05 Exam Rule Set: per course type the CIA/ESE maxima, pass thresholds, the attempt rule
(from attempt N the ESE alone decides) and revaluation eligibility; for the regulation the CIA
carry-forward, absence handling, maximum attempts and the Internal Only pass %. Locked once the
regulation is Effective."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.examinations.rule_lock import validate_rule_delete, validate_rule_lock


class ExamRuleSet(Document):
	def validate(self):
		validate_rule_lock(self)
		types = [row.course_type for row in self.types]
		if len(types) != len(set(types)):
			frappe.throw(_("Each course type may appear once."))
		for row in self.types:
			if row.cia_max < 0 or row.ese_max <= 0:
				frappe.throw(
					_("Row {0}: ESE maximum must be positive and CIA maximum not negative.").format(row.idx)
				)
			if not all(
				0 <= value <= 100 for value in (row.ese_min_pct, row.total_min_pct, row.ese_only_min_pct)
			):
				frappe.throw(_("Row {0}: percentages lie within 0-100.").format(row.idx))
			if row.ese_only_from_attempt and not row.ese_only_min_pct:
				frappe.throw(_("Row {0}: an ESE-alone attempt rule needs its ESE minimum %.").format(row.idx))
		if not 0 <= self.internal_only_min_pct <= 100:
			frappe.throw(_("The Internal Only pass % lies within 0-100."))

	def on_trash(self):
		validate_rule_delete(self)
