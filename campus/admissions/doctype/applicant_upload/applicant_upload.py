"""M04-06 Applicant Upload: a staff file of candidates, previewed then imported (campus.admissions.applicant_upload).

Status, run and summary fields are set only by the upload code (db writes); a user save can never change them.
"""

import frappe
from frappe import _
from frappe.model.document import Document

SYSTEM_FIELDS = ("status", "bulk_run", "file_sha256", "total_rows", "summary")
INPUT_FIELDS = ("company", "academic_year", "upload_file")


class ApplicantUpload(Document):
	def validate(self):
		if self.is_new():
			self.update(
				{"status": "Draft", "bulk_run": None, "file_sha256": None, "total_rows": 0, "summary": None}
			)
			return
		if any(self.has_value_changed(f) for f in SYSTEM_FIELDS):
			frappe.throw(
				_("The status of an upload is set by Validate and Import only."), frappe.PermissionError
			)
		if not any(self.has_value_changed(f) for f in INPUT_FIELDS):
			return
		if self.status not in ("Draft", "Validated"):
			frappe.throw(_("An imported upload cannot be changed."))
		self.status = "Draft"  # a new file, company or year needs a new preview
