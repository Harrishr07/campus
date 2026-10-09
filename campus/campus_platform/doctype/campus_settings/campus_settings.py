"""M17 Campus Settings (single)."""

import frappe
from frappe import _
from frappe.model.document import Document


class CampusSettings(Document):
	def validate(self):
		self.validate_evidence_sources()

	def validate_evidence_sources(self):
		"""A file field named for an Evidence Source must be an Attach field of that document type."""
		from campus.iqac.evidence import ATTACH_TYPES

		for row in self.get("evidence_sources") or []:
			if not row.file_field:
				continue
			field = frappe.get_meta(row.document_type).get_field(row.file_field)
			if not (field and field.fieldtype in ATTACH_TYPES):
				frappe.throw(_("Row {0}: {1} is not an Attach field of {2}.").format(row.idx, frappe.bold(row.file_field), frappe.bold(row.document_type)))
