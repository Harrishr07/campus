"""M04-06 Applicant Upload: a staff file of candidates, previewed then imported (campus.admissions.applicant_upload)."""

import frappe
from frappe import _
from frappe.model.document import Document


class ApplicantUpload(Document):
	def validate(self):
		if not self.is_new() and self.status != "Draft" and self.has_value_changed("upload_file"):
			if self.status != "Validated":
				frappe.throw(_("The file of an imported upload cannot be changed."))
			self.status = "Draft"  # a new file needs a new preview
