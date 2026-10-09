"""M01-05 Feedback Response: the answers of one respondent to a Feedback Campaign.

Written only by campus.iqac.feedback (straight inserts, no document hooks, versions or follows). An anonymous response
keeps no user, owner, record or time finer than the day; the one-response-each check lives in Feedback Response Token.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class FeedbackResponse(Document):
	def validate(self):
		frappe.throw(_("Feedback responses are recorded by the feedback form only and never change."))
