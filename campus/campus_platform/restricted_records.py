"""NFR Privacy (L-09) Restricted records: DocTypes whose read is decided by their own has_permission and permission
query hooks, listed under the `restricted_record_doctypes` hook. Frappe would still show them through generic side
doors; this closes those for every registered DocType:
- Comment: a comment on a restricted record is listed and read only by someone who can read the record;
- File: a File attached to one is listed and read only by a reader of the record (changed only by a writer), and is
  always private, whatever the uploader ticks;
- Connections (frappe.desk.form.linked_with.get): a related form never shows how many of them the caller cannot read.
"""

import frappe
from frappe.desk.form import linked_with

WRITE_TYPES = ("write", "create", "delete")


def restricted_doctypes():
	return frappe.get_hooks("restricted_record_doctypes") or []


# ---- Comment --------------------------------------------------------------------------------


def comment_permission_query(user=None, doctype=None):
	return reference_condition("Comment", "reference_doctype", "reference_name", user)


def comment_has_permission(doc, ptype=None, user=None, debug=False):
	return reference_allows(doc.reference_doctype, doc.reference_name, "read", user)


# ---- File -----------------------------------------------------------------------------------


def file_permission_query(user=None, doctype=None):
	return reference_condition("File", "attached_to_doctype", "attached_to_name", user)


def file_has_permission(doc, ptype=None, user=None, debug=False):
	"""Owning the File (e.g. a mentor who has since been reallocated) is not enough: the record decides."""
	return reference_allows(doc.attached_to_doctype, doc.attached_to_name, "write" if ptype in WRITE_TYPES else "read", user)


class PrivateAttachmentMixin:
	"""File: an attachment to a restricted record is always private (a public file is served to anyone by URL).
	Set before the upload is written to disk on insert, and before File.validate moves it when edited."""

	def before_insert(self):
		self.keep_private()
		super().before_insert()

	def validate(self):
		self.keep_private()
		super().validate()

	def keep_private(self):
		if self.attached_to_doctype in restricted_doctypes() and not self.is_folder:
			self.is_private = 1


# ---- Connections ----------------------------------------------------------------------------


@frappe.whitelist()
def get_linked_docs(doctype: str, docname: str):
	"""Override of frappe.desk.form.linked_with.get: a restricted DocType shows only the records the caller reads, and
	no hidden count; one with none readable is left out."""
	result = linked_with.get(doctype, docname)
	for restricted in restricted_doctypes():
		entry = result.get(restricted)
		if entry is None:
			continue
		if entry["docs"]:
			entry["hidden_count"] = 0
		else:
			del result[restricted]
	return result


# ---- shared ---------------------------------------------------------------------------------


def reference_allows(doctype, name, ptype, user=None):
	user = user or frappe.session.user
	if doctype not in restricted_doctypes() or user == "Administrator":
		return True
	if not name or not frappe.db.exists(doctype, name):
		return False  # an orphan of a deleted restricted record stays hidden
	return bool(frappe.has_permission(doctype, ptype, doc=name, user=user))


def reference_condition(table, doctype_field, name_field, user=None):
	"""SQL: the row refers to no restricted DocType, or to a record of one that the user can read."""
	user = user or frappe.session.user
	doctypes = restricted_doctypes()
	if user == "Administrator" or not doctypes:
		return ""
	doctype_col, name_col = f"`tab{table}`.`{doctype_field}`", f"`tab{table}`.`{name_field}`"
	listed = ", ".join(frappe.db.escape(dt) for dt in doctypes)
	clauses = [f"ifnull({doctype_col}, '') not in ({listed})"]
	for doctype in doctypes:
		if readable := readable_names_sql(doctype, user):
			clauses.append(f"({doctype_col} = {frappe.db.escape(doctype)} and {name_col} in ({readable}))")
	return f"({' or '.join(clauses)})"


def readable_names_sql(doctype, user):
	"""Sub-select of the names the user may list (role, User Permissions and the DocType's own query hooks), or None."""
	if not frappe.has_permission(doctype, "read", user=user):
		return None
	return frappe.qb.get_query(doctype, fields=["name"], user=user, ignore_permissions=False).get_sql()
