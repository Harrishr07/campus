"""M17-03 Approval Delegation: a user's approvals may be acted on by a delegate within a date window."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class ApprovalDelegation(Document):
	def validate(self):
		if self.user == self.delegate:
			frappe.throw(_("A user cannot delegate to themselves."))
		if getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(_("From Date must be on or before To Date."))
		if self.user != frappe.session.user and "System Manager" not in frappe.get_roles():
			frappe.throw(_("You can only delegate your own approvals."), frappe.PermissionError)
