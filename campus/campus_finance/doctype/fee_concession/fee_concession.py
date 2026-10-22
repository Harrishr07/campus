"""M05-05 Fee Concession: a discount on a student's fee category, approved through the approval engine.

Only fee categories flagged `oc_concession_allowed` can be conceded. It cannot be submitted without an approved
approval request (an Approval Policy for the doctype must exist). Once submitted it waits as Open; the next fee invoice
of the student in the academic year gets a discount on its line of that category (campus.campus_finance.concessions) and the concession turns
Applied. An applied concession cannot be cancelled until its invoice is.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission
from frappe.utils import flt

from campus.campus_platform.api import ApprovableDocument, is_approved


class FeeConcession(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		if self.docstatus == 0:
			self.set_company()
			self.check_category()
			self.check_value()

	def before_submit(self):
		super().before_submit()
		if not is_approved(self):
			frappe.throw(_("{0} needs approval before it can be submitted. Use Request Approval.").format(self.name))

	def before_cancel(self):
		if self.status == "Applied":
			frappe.throw(_("{0} is applied to invoice {1}; cancel the invoice first.").format(self.name, self.applied_invoice))

	def set_company(self):
		student = frappe.get_doc("Student", self.student)
		if not has_user_permission(student):  # Company User Permissions
			frappe.throw(_("You are not permitted to give a concession to {0}.").format(frappe.bold(self.student)), frappe.PermissionError)
		self.company = student.oc_company

	def check_category(self):
		if not frappe.db.get_value("Fee Category", self.fee_category, "oc_concession_allowed"):
			frappe.throw(_("Fee category {0} is not configured for concessions.").format(frappe.bold(self.fee_category)))

	def check_value(self):
		if self.concession_type == "Percent":
			self.amount = 0
			if not 0 < flt(self.percent) <= 100:
				frappe.throw(_("The concession percent must be above 0 and at most 100."))
		else:
			self.percent = 0
			if flt(self.amount) <= 0:
				frappe.throw(_("The concession amount must be positive."))
