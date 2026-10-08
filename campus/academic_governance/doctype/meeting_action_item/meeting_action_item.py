"""M02-03 Meeting Action Item: something a meeting asked a person to do, by a due date; overdue open items are
reminded weekly (campus.academic_governance.actions)."""

import frappe
from frappe import _
from frappe.model.document import Document


class MeetingActionItem(Document):
	def validate(self):
		if self.status == "Done" and not self.action_taken:
			frappe.throw(_("Record the action taken before marking the item Done"))
