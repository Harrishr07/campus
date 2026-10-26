"""M05-01 Student Onboarding: one per student; completion % is mirrored on the Student form."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


class StudentOnboarding(Document):
	def validate(self):
		for row in self.items:
			self.check_item(row)
		self.completion = completion_percent(self.items)

	def check_item(self, row):
		if row.status == "Waived" and row.mandatory:
			frappe.throw(_("Row {0}: {1} is mandatory and cannot be waived.").format(row.idx, row.title))
		if row.status == "Done":
			if row.requires_attachment and not row.attachment:
				frappe.throw(
					_("Row {0}: {1} needs an attachment before it is marked Done.").format(row.idx, row.title)
				)
			row.done_by = row.done_by or frappe.session.user
			row.done_on = row.done_on or now_datetime()
		else:
			row.done_by = row.done_on = None

	def on_update(self):
		frappe.db.set_value(
			"Student", self.student, "oc_onboarding_completion", self.completion, update_modified=False
		)

	def on_trash(self):
		frappe.db.set_value("Student", self.student, "oc_onboarding_completion", 0, update_modified=False)


def completion_percent(items):
	"""Done / (all - Waived) as a percentage; a checklist with nothing left to do is 100."""
	counted = [row for row in items if row.status != "Waived"]
	if not counted:
		return 100.0
	return flt(100 * sum(row.status == "Done" for row in counted) / len(counted), 2)
