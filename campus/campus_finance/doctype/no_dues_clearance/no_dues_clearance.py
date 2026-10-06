"""M09-04 No Dues Clearance: sign-off by each office and a dues check before a no-dues certificate is issued.

Dues are checked on every save and again on submit across all companies of the student's Customer. Submitting
needs every mandatory office Cleared and no dues; it then issues the verifiable "No Dues Certificate".
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import fmt_money, now_datetime

from campus.campus_finance import ledger
from campus.campus_platform import verification

CLEARED, PENDING = "Cleared", "Pending"
STANDARD_OFFICES = ("Accounts", "Library", "Hostel", "Lab")
CERTIFICATE_FORMAT = "No Dues Certificate"


class NoDuesClearance(Document):
	def validate(self):
		self.add_standard_offices()
		self.stamp_signoffs()
		self.check_dues()

	def before_submit(self):
		self.check_dues()
		pending = [row.office for row in self.signoffs if row.mandatory and row.status != CLEARED]
		if pending:
			frappe.throw(_("Sign-off pending from: {0}").format(", ".join(pending)))
		if self.dues_total > 0:
			frappe.throw(_("The student has dues of {0}; they must be paid first.").format(fmt_money(self.dues_total, currency="INR")))

	def on_submit(self):
		self.db_set("verification_code", verification.issue(self, CERTIFICATE_FORMAT).code)

	def add_standard_offices(self):
		if self.is_new() and not self.signoffs:
			for office in STANDARD_OFFICES:
				self.append("signoffs", {"office": office, "mandatory": 1, "status": PENDING})

	def stamp_signoffs(self):
		"""Who cleared a row and when is set by the server, whenever a row becomes Cleared; reset on Pending."""
		before = self.get_doc_before_save()
		earlier = {row.name: row.status for row in before.signoffs} if before else {}
		for row in self.signoffs:
			if row.status != CLEARED:
				row.cleared_by = row.cleared_on = None
			elif earlier.get(row.name) != CLEARED:
				row.cleared_by, row.cleared_on = frappe.session.user, now_datetime()

	def check_dues(self):
		dues = ledger.has_dues(self.student)
		self.dues_total, self.dues_checked_on = dues.total, now_datetime()
		self.dues_note = ", ".join(f"{head}: {amount}" for head, amount in dues.by_head.items()) or None
