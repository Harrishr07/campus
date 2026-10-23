"""PR-08 UAT Feedback: one row per mismatch an intern finds while walking a UAT script (docs/usage/uat)."""

import frappe
from frappe.model.document import Document


class UATFeedback(Document):
	def before_insert(self):
		self.tester_role = self.tester_role or frappe.session.user
