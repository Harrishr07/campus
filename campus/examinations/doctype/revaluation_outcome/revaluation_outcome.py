"""M06-06 Revaluation Outcome: the revaluer's ESE of one course of a paid Revaluation or Review. On submit the
student's result is recomputed: after publication a change is a pending Student Result version for a Result
Ratification (rules: campus.examinations.revaluation). Not cancellable."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.examinations import revaluation


class RevaluationOutcome(Document):
	def validate(self):
		revaluation.validate_outcome(self)

	def on_submit(self):
		revaluation.apply_outcome(self)

	def before_cancel(self):
		frappe.throw(_("A Revaluation Outcome cannot be cancelled: its result version goes to ratification."))
