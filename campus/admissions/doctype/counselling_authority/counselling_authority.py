"""M04-01 Counselling Authority: an allotment source and the column mapping of its import file."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.admissions.aadhaar import AADHAAR_FIELD, MASKED_FIELD


class CounsellingAuthority(Document):
	def validate(self):
		meta = frappe.get_meta("Student Applicant")
		seen = set()
		for row in self.column_mapping:
			if row.source_column in seen:
				frappe.throw(_("Row {0}: column {1} is mapped twice.").format(row.idx, row.source_column))
			seen.add(row.source_column)
			if row.target_field in (AADHAAR_FIELD, MASKED_FIELD):
				frappe.throw(_("Row {0}: Aadhaar numbers are never imported from allotment files.").format(row.idx))
			if not meta.has_field(row.target_field):
				frappe.throw(_("Row {0}: Student Applicant has no field {1}.").format(row.idx, row.target_field))
