"""M09-04 No Dues Clearance: sign-off by each office and a dues check before a no-dues certificate is issued.

Dues are checked on every save and again on submit across all companies of the student's Customer. The standard
offices are always present and mandatory, and each office is cleared only by its roles (Campus Settings).
Submitting needs every mandatory office Cleared and no dues owed to any company; it then issues the verifiable
"No Dues Certificate", which is revoked if the clearance is cancelled.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import fmt_money, now_datetime

from campus.campus_finance import ledger, no_dues
from campus.campus_platform import verification

CLEARED, PENDING = "Cleared", "Pending"
CERTIFICATE_FORMAT = "No Dues Certificate"


class NoDuesClearance(Document):
	def validate(self):
		self.ensure_standard_offices()
		self.stamp_signoffs()
		self.check_dues()

	def before_submit(self):
		self.check_dues()
		pending = [row.office for row in self.signoffs if row.mandatory and row.status != CLEARED]
		if pending:
			frappe.throw(_("Sign-off pending from: {0}").format(", ".join(pending)))
		if self.dues_total > 0:
			currency = frappe.get_cached_value("Company", self.company, "default_currency") if self.company else None
			frappe.throw(_("The student has dues of {0}; they must be paid first.").format(fmt_money(self.dues_total, currency=currency)))

	def on_submit(self):
		self.db_set("verification_code", verification.issue(self, CERTIFICATE_FORMAT).code)

	def on_cancel(self):
		verification.revoke_for(self, _("No Dues Clearance {0} was cancelled.").format(self.name))

	def ensure_standard_offices(self):
		"""A new clearance gets the standard offices; offices are unique, and none of the standard ones may be
		removed, renamed or made optional."""
		if self.is_new():
			listed = {no_dues.normalise(row.office) for row in self.signoffs}
			for office in no_dues.STANDARD_OFFICES:
				if no_dues.normalise(office) not in listed:
					self.append("signoffs", {"office": office, "mandatory": 1, "status": PENDING})
		offices = [no_dues.normalise(row.office) for row in self.signoffs]
		for office in set(offices):
			if offices.count(office) > 1:
				frappe.throw(_("The office {0} is listed more than once.").format(office.title()))
		present = dict(zip(offices, self.signoffs, strict=True))
		for office in no_dues.STANDARD_OFFICES:
			row = present.get(no_dues.normalise(office))
			if row is None:
				frappe.throw(_("The {0} sign-off is required and cannot be removed.").format(office))
			if not row.mandatory:
				frappe.throw(_("The {0} sign-off is mandatory.").format(office))

	def stamp_signoffs(self):
		"""Who cleared a row and when is set by the server, whenever a row becomes Cleared; reset on Pending.

		Changing a row's status needs one of the office's roles (managers only for an office with no mapping).
		Renaming a row's office is a change of both offices: it needs the old office's roles if the row was
		Cleared, and the row stays Cleared only if the user may clear the new office.
		"""
		before = self.get_doc_before_save()
		earlier = {row.name: (row.status, row.office) for row in before.signoffs} if before else {}
		for row in self.signoffs:
			old_status, old_office = earlier.get(row.name, (PENDING, row.office))
			renamed = no_dues.normalise(old_office) != no_dues.normalise(row.office)
			if old_status == row.status and not renamed:
				continue
			if old_status == CLEARED:
				no_dues.check_may_clear(old_office)
			if row.status == CLEARED and renamed and not no_dues.may_clear(row.office):
				row.status = PENDING
			elif row.status == CLEARED:
				no_dues.check_may_clear(row.office)
			if row.status == CLEARED:
				row.cleared_by, row.cleared_on = frappe.session.user, now_datetime()
			else:
				row.cleared_by = row.cleared_on = None

	def check_dues(self):
		dues = ledger.has_dues(self.student)
		self.dues_total, self.dues_checked_on = dues.blocking, now_datetime()
		self.dues_note = ", ".join(f"{head}: {amount}" for head, amount in dues.by_head.items()) or None
