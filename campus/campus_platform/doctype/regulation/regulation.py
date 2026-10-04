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


def regulation_name(code, company):
	"""Document name of the regulation `code` of `company`: codes repeat across colleges."""
	return f"{code}-{frappe.db.get_value('Company', company, 'abbr')}"


class Regulation(Document):
	def autoname(self):
		self.validate_unique_code()  # the name would collide before validate runs
		self.name = regulation_name(self.code, self.company)

	def validate(self):
		self.validate_unique_code()
		self.validate_unique_programs()
		self.validate_effective_lock()

	def on_update(self):
		if self.status == "Effective":
			self.retire_previous_version()

	def on_trash(self):
		if self.status in ("Effective", "Retired"):
			frappe.throw(_("An {0} regulation cannot be deleted.").format(_(self.status)))

	def validate_unique_code(self):
		clash = frappe.db.exists(
			"Regulation", {"code": self.code, "company": self.company, "name": ["!=", self.name or ""]}
		)
		if clash:
			frappe.throw(
				_("Regulation code {0} already exists for {1}.").format(
					frappe.bold(self.code), frappe.bold(self.company)
				)
			)

	def validate_unique_programs(self):
		programs = [row.program for row in self.programs]
		if len(programs) != len(set(programs)):
			frappe.throw(_("A program is listed more than once."))

	def validate_effective_lock(self):
		before = self.get_doc_before_save()
		if before and before.status == "Retired" and self.status != "Retired":
			frappe.throw(_("A Retired regulation cannot be reinstated. Amend it as a new version."))
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
		if (
			self.previous_version
			and frappe.db.get_value("Regulation", self.previous_version, "status") == "Effective"
		):
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
	new.code = next_version_code(source.code, source.company)
	new.status = "Draft"
	new.previous_version = source.name
	for row in source.programs:
		new.append("programs", {"program": row.program})
	return new.insert().name


def next_version_code(code, company):
	base = re.sub(r"-V\d+$", "", code)
	version = 2
	while frappe.db.exists("Regulation", {"code": f"{base}-V{version}", "company": company}):
		version += 1
	return f"{base}-V{version}"
