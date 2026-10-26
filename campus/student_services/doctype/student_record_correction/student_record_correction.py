"""M05-11 Student Record Correction: one field of a student's record (or of a guardian's) changed through approval.
Rules and the apply service: campus.student_services.corrections."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_platform.api import ApprovableDocument
from campus.student_services import corrections

FROZEN = (corrections.PENDING, corrections.APPROVED, corrections.REJECTED, corrections.APPLIED)
SERVER_FIELDS = ("status", "requested_via", "new_secret", "applied_on", "applied_by", "version")


class StudentRecordCorrection(ApprovableDocument, Document):
	def validate(self):
		self.keep_server_fields()
		super().validate()
		if self.status == corrections.REJECTED:
			frappe.throw(
				_(
					"{0} was rejected and is kept as the record of the refusal; raise a new correction."
				).format(self.name)
			)
		if self.status in FROZEN:
			return  # frozen by the approval; guard_edits already refused changes
		if not self.flags.from_portal:
			corrections.check_desk_access(self)  # before prepare, which reads the student's current values
		corrections.prepare(self)

	def keep_server_fields(self):
		"""Only the server sets these (the approval, raise_correction, store_aadhaar, apply_correction); a value sent
		by the client is replaced by the stored one."""
		before = None if self.is_new() else self.get_doc_before_save()
		for field in SERVER_FIELDS:
			self.set(field, before.get(field) if before else None)
		if not before:
			self.status = corrections.DRAFT
			self.requested_via = "Portal" if self.flags.from_portal else "Desk"

	def before_submit(self):
		frappe.throw(_("A correction is applied by its approval; it is not submitted."))

	def before_approval_request(self):
		corrections.before_request(self)

	def on_trash(self):
		if self.status in FROZEN:
			frappe.throw(_("A correction that was sent for approval is kept as the record of the change."))
		super().on_trash()
