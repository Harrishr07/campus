"""M05-12 Attendance Correction Request: one student's mark of one period changed after the correction cut-off, with
the HOD's approval. Rules and the apply service: campus.faculty.attendance_corrections."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission

from campus.campus_platform.api import ApprovableDocument, is_approved
from campus.faculty import attendance_corrections as corrections


class AttendanceCorrectionRequest(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		if self.docstatus != 0:
			return  # the approval-driven submit must not re-judge an approved request
		if not self.flags.ignore_permissions:
			if not has_user_permission(frappe.get_doc("Student", self.student)):
				frappe.throw(
					_("You are not permitted to act for {0}.").format(frappe.bold(self.student)),
					frappe.PermissionError,
				)
			corrections.check_requester(self)
		corrections.prepare(self)

	def before_approval_request(self):
		corrections.before_request(self)

	def before_submit(self):
		super().before_submit()
		if not is_approved(self):
			frappe.throw(_("An attendance correction is applied only after its approval."))

	def on_submit(self):
		corrections.apply(self)

	def before_cancel(self):
		frappe.throw(_("An applied attendance correction is kept as the record of the change."))
