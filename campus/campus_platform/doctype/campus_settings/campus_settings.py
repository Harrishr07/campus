"""M17 Campus Settings (single)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class CampusSettings(Document):
	def validate(self):
		self.validate_evidence_sources()
		self.validate_feedback_group_size()
		self.validate_approval_required_doctypes()

	def validate_feedback_group_size(self):
		"""Feedback groups smaller than 3 would let one respondent's answer show (M01-05 anonymity). A blank value is
		the default, not an error."""
		from campus.iqac.api import MINIMUM_GROUP_DEFAULT, MINIMUM_GROUP_FLOOR

		if not cint(self.feedback_minimum_group_size):
			self.feedback_minimum_group_size = MINIMUM_GROUP_DEFAULT
		if cint(self.feedback_minimum_group_size) < MINIMUM_GROUP_FLOOR:
			frappe.throw(_("Feedback Minimum Group Size must be at least {0}.").format(MINIMUM_GROUP_FLOOR))

	def validate_evidence_sources(self):
		"""A file field named for an Evidence Source must be an Attach field of that document type."""
		from campus.iqac.evidence import ATTACH_TYPES

		for row in self.get("evidence_sources") or []:
			if not row.file_field:
				continue
			field = frappe.get_meta(row.document_type).get_field(row.file_field)
			if not (field and field.fieldtype in ATTACH_TYPES):
				frappe.throw(
					_("Row {0}: {1} is not an Attach field of {2}.").format(
						row.idx, frappe.bold(row.file_field), frappe.bold(row.document_type)
					)
				)

	def validate_approval_required_doctypes(self):
		"""NFR Mandatory approval: only document types approved through the approval engine can require a policy."""
		from campus.campus_platform.mandatory_approval import uses_approval_engine

		for row in self.get("approval_required_doctypes") or []:
			if not uses_approval_engine(row.document_type):
				frappe.throw(
					_("Row {0}: {1} does not use the approval engine.").format(
						row.idx, frappe.bold(row.document_type)
					)
				)
