"""M01-01 Evidence: a file or URL that supports accreditation answers, with a stable public URL /disclosure/<slug>.

The slug is the name, made once from the title and never changed, so the public URL survives renames and replaced source files.
An Evidence linked to a source record (and its Attach field) always serves that field's current file. Only IQAC staff can make an
Evidence public, and only an evidence whose file is public.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.iqac import evidence as registry


class Evidence(Document):
	def autoname(self):
		self.slug = registry.unique_slug(self.title)
		self.name = self.slug

	def validate(self):
		self.public_url = f"/disclosure/{self.slug}"
		self.evidence_owner = self.evidence_owner or frappe.session.user
		self.validate_content()
		self.validate_nodes()
		self.validate_public()

	def validate_content(self):
		if self.kind == "URL":
			if not registry.is_web_url(self.url):
				frappe.throw(_("A URL evidence needs a web address starting with http:// or https://."))
			self.file = self.source_field = None
		elif self.source_field:
			self.validate_source()
		elif not self.file:
			frappe.throw(_("A file evidence needs its file."))

	def validate_source(self):
		field = frappe.get_meta(self.source_doctype).get_field(self.source_field) if self.source_doctype else None
		if not (field and field.fieldtype in registry.ATTACH_TYPES and self.source_name):
			frappe.throw(_("{0} is not an Attach field of {1}.").format(frappe.bold(self.source_field), frappe.bold(self.source_doctype)))
		self.file = None

	def validate_nodes(self):
		for row in self.nodes:
			slot = frappe.db.get_value(
				"Framework Node Evidence Slot", {"parenttype": "Framework Node", "parent": row.node, "slot_name": row.slot_name}, "kind"
			)
			if not slot:
				frappe.throw(_("Row {0}: {1} has no evidence slot {2}.").format(row.idx, frappe.bold(row.node), frappe.bold(row.slot_name)))
			if slot != self.kind:
				frappe.throw(_("Row {0}: slot {1} takes a {2}, this evidence is a {3}.").format(row.idx, frappe.bold(row.slot_name), slot, self.kind))

	def validate_public(self):
		if not self.is_public:
			return
		if self.is_new() or self.has_value_changed("is_public"):
			registry.check_may_publish()
		if self.kind == "File" and (file := registry.current_file(self)) and not registry.is_public_file(file):
			frappe.throw(_("The file is private; a public evidence needs a public file."))
