"""M04-07 Candidate Duplicate Review: a possible duplicate candidate awaiting a Link / Not Duplicate decision.

The decision is taken only through campus.admissions.duplicates.decide (Admission Officer), which stamps who
decided, when and why. No role has write permission, and a saved review refuses any other change.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class CandidateDuplicateReview(Document):
	def validate(self):
		if not self.is_new() and not self.flags.from_decide:
			frappe.throw(_("A duplicate review changes only through its Link or Not Duplicate decision."), frappe.PermissionError)
