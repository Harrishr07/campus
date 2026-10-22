"""M01-05 Feedback Response Token: one row per respondent who answered a campaign, so nobody answers twice.

The name is a keyed hash of campaign and respondent (campus.iqac.feedback.token_name); the row keeps nothing else, and
its owner and times are fixed values, so it cannot be matched to a response.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class FeedbackResponseToken(Document):
	def validate(self):
		frappe.throw(_("Feedback response tokens are recorded by the feedback form only."))
