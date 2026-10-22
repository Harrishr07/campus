"""M05-09 Lifecycle Transition: one change of a student's lifecycle status (from, to, effective date, reason,
source document, approver). History (NFR history preservation): written only by campus.student_services.lifecycle,
never edited or deleted; a mistake is undone by a Reversal record that names the transition it reverses."""

import frappe
from frappe import _
from frappe.model.document import Document


class LifecycleTransition(Document):
	def validate(self):
		if not self.flags.from_lifecycle_service:
			frappe.throw(_("Lifecycle Transitions are recorded by the lifecycle service only."))

	def on_trash(self):
		frappe.throw(_("A Lifecycle Transition is history and cannot be deleted."))
