"""M05-09 Lifecycle Transition Rule: one permitted change of a student's lifecycle status (the configurable
transition table). A blank From Status is the first status of a new Student record. Only enabled rules permit."""

import frappe
from frappe import _
from frappe.model.document import Document


class LifecycleTransitionRule(Document):
	def autoname(self):
		from campus.student_services.lifecycle import rule_name

		self.name = rule_name(self.from_status, self.to_status)

	def validate(self):
		if (self.from_status or "") == self.to_status:
			frappe.throw(_("The From and To statuses cannot be the same."))
