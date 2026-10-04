"""M02-04 Regulation: the rule-set anchor every academic rule resolves through (principle 4).

An Effective regulation is locked; it can only be retired or amended as a new Draft version.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

NO_VALUE_FIELDS = frappe.model.no_value_fields
NEW_VERSION_FIELDS = ("company", "effective_from_year", "approving_resolution", "notes")


class Regulation(Document):
	def validate(self):
		self.validate_unique_programs()
		self.validate_effective_lock()

	def on_update(self):
		if self.status == "Effective":
			self.retire_previous_version()

	def validate_unique_programs(self):
		programs = [row.program for row in self.programs]
		if len(programs) != len(set(programs)):
			frappe.throw(_("A program is listed more than once."))

	def validate_effective_lock(self):
		before = self.get_doc_before_save()
		if not before or before.status != "Effective":
			return
		if self.status not in ("Effective", "Retired"):
			frappe.throw(_("An Effective regulation can only be retired."))
		if self.snapshot() != before.snapshot():
			frappe.throw(
				_("{0} is Effective and cannot be edited. Amend it as a new version instead.").format(
					frappe.bold(self.name)
				),
				title=_("Regulation Locked"),
			)

	def snapshot(self):
		"""Editable content of the document, excluding status."""
		values = {
			df.fieldname: cstr(self.get(df.fieldname))
			for df in self.meta.fields
			if df.fieldtype not in NO_VALUE_FIELDS and df.fieldname != "status"
		}
		values["programs"] = sorted(row.program for row in self.programs)
		return values

	def retire_previous_version(self):
		if self.previous_version and frappe.db.get_value("Regulation", self.previous_version, "status") == "Effective":
			frappe.db.set_value("Regulation", self.previous_version, "status", "Retired")


@frappe.whitelist()
def amend_as_new_version(regulation):
	"""Copy `regulation` into a new Draft version linked back through `previous_version`."""
	frappe.has_permission("Regulation", "create", throw=True)
	source = frappe.get_doc("Regulation", regulation)
	frappe.has_permission("Regulation", "read", doc=source, throw=True)
	if source.status not in ("Approved", "Effective"):
		frappe.throw(_("Only an Approved or Effective regulation can be amended."))
	new = frappe.new_doc("Regulation")
	new.update({field: source.get(field) for field in NEW_VERSION_FIELDS})
	new.code = next_version_code(source.code)
	new.status = "Draft"
	new.previous_version = source.name
	for row in source.programs:
		new.append("programs", {"program": row.program})
	return new.insert().name


def next_version_code(code):
	base = re.sub(r"-V\d+$", "", code)
	version = 2
	while frappe.db.exists("Regulation", f"{base}-V{version}"):
		version += 1
	return f"{base}-V{version}"
