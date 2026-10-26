"""M01-01 Evidence: a file or URL that supports accreditation answers, with a stable public URL /disclosure/<slug>.

The slug is the name, made once from the title and never changed, so the public URL survives renames and replaced source files.
An Evidence linked to a source record (and its Attach field) always serves that field's current file. Only IQAC staff can make an
Evidence public, and only an evidence whose file is public.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_platform.company_scope import permitted_companies
from campus.iqac import evidence as registry


class Evidence(Document):
	def autoname(self):
		self.slug = registry.unique_slug(self.title)
		self.name = self.slug

	def validate(self):
		self.public_url = f"/disclosure/{self.slug}"
		self.evidence_owner = self.evidence_owner or frappe.session.user
		self.validate_content()
		self.validate_source()
		self.validate_nodes()
		self.validate_public()

	def validate_content(self):
		if self.kind == "URL":
			if not registry.is_web_url(self.url):
				frappe.throw(_("A URL evidence needs a web address starting with http:// or https://."))
			self.file = self.source_field = None
		elif self.source_field:
			pass  # the file is read from the source (see validate_source)
		elif not self.file:
			frappe.throw(_("A file evidence needs its file."))

	def validate_source(self):
		"""Whatever the write path (desk, REST, import), when the source or company changes: the source type is listed in
		Campus Settings, the user may read the record, and the evidence belongs to the source's company. An evidence without
		a source belongs to a company the user is permitted for (so it never fills another college's slots). A source type
		delisted later does not block saving an evidence whose source is unchanged."""
		if not self.source_doctype:
			if self.source_name or self.source_field:
				frappe.throw(_("A source record or field needs its source document type."))
			if self.source_changed():
				self.check_company_permitted()
			return
		if self.source_field:
			self.file = None
		if not self.source_changed():
			return
		listed = registry.source_file_field(self.source_doctype)
		frappe.has_permission(self.source_doctype, "read", self.source_name, throw=True)
		company = registry.source_company(self.source_doctype, self.source_name)
		if self.company != company:
			frappe.throw(
				_("The company of the evidence must be the company of its source, {0}.").format(
					frappe.bold(company)
				)
			)
		if self.source_field:
			field = frappe.get_meta(self.source_doctype).get_field(self.source_field)
			if self.source_field != listed or not (
				field and field.fieldtype in registry.ATTACH_TYPES and self.source_name
			):
				frappe.throw(
					_("{0} is not the listed Attach field of {1}.").format(
						frappe.bold(self.source_field), frappe.bold(self.source_doctype)
					)
				)

	def source_changed(self):
		return self.is_new() or any(
			self.has_value_changed(f) for f in ("source_doctype", "source_name", "source_field", "company")
		)

	def check_company_permitted(self):
		permitted = permitted_companies(frappe.session.user)
		if permitted is not None and self.company not in permitted:
			frappe.throw(
				_("You are not permitted to add evidence for {0}.").format(frappe.bold(self.company)),
				frappe.PermissionError,
			)

	def validate_nodes(self):
		for row in self.nodes:
			slot = frappe.db.get_value(
				"Framework Node Evidence Slot",
				{"parenttype": "Framework Node", "parent": row.node, "slot_name": row.slot_name},
				"kind",
			)
			if not slot:
				frappe.throw(
					_("Row {0}: {1} has no evidence slot {2}.").format(
						row.idx, frappe.bold(row.node), frappe.bold(row.slot_name)
					)
				)
			if slot != self.kind:
				frappe.throw(
					_("Row {0}: slot {1} takes a {2}, this evidence is a {3}.").format(
						row.idx, frappe.bold(row.slot_name), slot, self.kind
					)
				)

	def validate_public(self):
		"""Any save of an evidence that is public before or after the save needs IQAC publish rights (it could retarget the file)."""
		before = self.get_doc_before_save()
		if self.is_public or (before and before.is_public):
			registry.check_may_publish()
		if (
			self.is_public
			and self.kind == "File"
			and (file := registry.current_file(self))
			and not registry.is_public_file(file)
		):
			frappe.throw(_("The file is private; a public evidence needs a public file."))
