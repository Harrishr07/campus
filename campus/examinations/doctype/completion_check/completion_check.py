"""M05-15 Completion Check: one credit completion check of a student against the curriculum (per-category earned vs
required, mandatory courses not cleared, Complete / Incomplete). Audit history: written only by
campus.examinations.completion, never edited or deleted."""

import frappe
from frappe import _
from frappe.model.document import Document


class CompletionCheck(Document):
	def validate(self):
		if not self.flags.from_completion_service:
			frappe.throw(_("Completion Checks are recorded by the completion service only."))

	def on_trash(self):
		frappe.throw(_("A Completion Check is kept for audit and cannot be deleted."))
