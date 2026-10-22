"""M05-11 Student Record Correction: one field of a student's record (or of a guardian's) changed through approval.
Rules and the apply service: campus.student_services.corrections."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission

from campus.campus_platform.api import ApprovableDocument
from campus.student_services import corrections


class StudentRecordCorrection(ApprovableDocument, Document):
	def validate(self):
		self.status = corrections.DRAFT if self.is_new() else self.get_doc_before_save().status  # set by the approval only
		super().validate()
		if self.status in (corrections.PENDING, corrections.APPROVED, corrections.APPLIED):
			return  # frozen by the approval; guard_edits already refused changes
		if self.requested_via != "Portal" and not has_user_permission(frappe.get_doc("Student", self.student)):
			frappe.throw(_("You are not permitted to act for {0}.").format(frappe.bold(self.student)), frappe.PermissionError)
		corrections.prepare(self)

	def before_submit(self):
		frappe.throw(_("A correction is applied by its approval; it is not submitted."))

	def before_approval_request(self):
		corrections.before_request(self)

	def on_trash(self):
		if self.status in (corrections.PENDING, corrections.APPROVED, corrections.APPLIED):
			frappe.throw(_("A correction that was sent for approval is kept as the record of the change."))
		super().on_trash()
