"""NFR Privacy (L-09) Restricted records: DocTypes whose read is decided by their own has_permission and permission
query hooks, listed under the `restricted_record_doctypes` hook. Frappe would still show them through generic side
doors; this closes those for every registered DocType:
- Comment: a comment on a restricted record is listed and read only by someone who can read the record;
- File: a File attached to one is listed and read only by a reader of the record (changed only by a writer), and is
  always private, whatever the uploader ticks. Its URL is downloaded or zipped only by a reader of such a record, even
  through another File row with the same URL or by the File's owner; only a reader adds such a row; it cannot be
  made public or detached, and the attached row is not deleted while other rows carry its URL;
- Sharing: neither a restricted record nor such a File can be shared (a share grants what the hooks refuse);
- Connections (frappe.desk.form.linked_with.get) and dashboard counts (frappe.desk.notifications.get_open_count):
  a related form shows only the records the caller can read, never how many it cannot.
"""

import frappe
from frappe import _
from frappe.desk import notifications
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
	if doc.attached_to_doctype in restricted_doctypes():
		return reference_allows(doc.attached_to_doctype, doc.attached_to_name, "write" if ptype in WRITE_TYPES else "read", user)
	return url_readable(doc.file_url, user, exclude=doc.name)


class PrivateAttachmentMixin:
	"""File: an attachment to a restricted record is always private (a public file is served to anyone by URL).
	Set before the upload is written to disk on insert, and before File.validate moves it when edited."""

	def before_insert(self):
		self.refuse_foreign_copy()
		self.keep_private()
		super().before_insert()

	def on_trash(self):
		self.refuse_orphaning_copies()
		super().on_trash()

	def validate(self):
		self.refuse_detaching()
		self.keep_private()
		super().validate()

	def is_downloadable(self):
		"""Frappe's download by URL checks only File's own rule (owner, share, attached record): add ours."""
		return super().is_downloadable() and file_has_permission(self, "read")

	def keep_private(self):
		if self.is_folder or self.is_private:
			return
		if self.attached_to_doctype in restricted_doctypes():
			self.is_private = 1
		elif restricted_attachments(self.file_url, exclude=self.name):
			frappe.throw(_("This file belongs to a confidential record and cannot be made public."), frappe.PermissionError)

	def refuse_foreign_copy(self):
		"""Frappe lets the owner of the first row add another row for a private URL; the record decides instead."""
		if not url_readable(self.file_url, exclude=self.name):
			frappe.throw(_("This file belongs to a confidential record you cannot read."), frappe.PermissionError)

	def refuse_orphaning_copies(self):
		"""The guard follows the attached row: deleting it would leave other rows with its URL unguarded."""
		if self.attached_to_doctype not in restricted_doctypes() or not self.file_url:
			return
		others = frappe.get_all("File", {"file_url": self.file_url, "name": ["!=", self.name]}, pluck="attached_to_doctype")
		if any(doctype not in restricted_doctypes() for doctype in others):
			frappe.throw(_("Delete the other File rows with this URL first: it belongs to a confidential record."), frappe.PermissionError)

	def refuse_detaching(self):
		before = self.get_doc_before_save()
		if before and before.attached_to_doctype in restricted_doctypes():
			if (before.attached_to_doctype, before.attached_to_name) != (self.attached_to_doctype, self.attached_to_name):
				frappe.throw(_("A file of a confidential record cannot be moved to another record."), frappe.PermissionError)


def block_share(doc, method=None):
	"""DocShare validate: a restricted record, or a File of one, is never shared."""
	if doc.share_doctype in restricted_doctypes():
		frappe.throw(_("{0} records cannot be shared.").format(_(doc.share_doctype)), frappe.PermissionError)
	if doc.share_doctype == "File" and doc.share_name:
		attached_to, file_url = frappe.db.get_value("File", doc.share_name, ["attached_to_doctype", "file_url"]) or (None, None)
		if attached_to in restricted_doctypes() or restricted_attachments(file_url):
			frappe.throw(_("A file of a confidential record cannot be shared."), frappe.PermissionError)


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


@frappe.whitelist()
def zip_files(files: str):
	"""Override of frappe.core.api.file.zip_files (and its legacy path), which checks only File's own rule: keep the
	Files the caller may read through every permission hook."""
	from frappe.core.api.file import zip_files as frappe_zip_files

	names = frappe.parse_json(files) or []
	readable = [n for n in names if isinstance(n, str) and frappe.db.exists("File", n) and frappe.has_permission("File", "read", doc=n)]
	return frappe_zip_files(frappe.as_json(readable))


@frappe.whitelist()
@frappe.read_only()
def get_open_count(doctype: str, name: str | int, items: str | list[str] | None = None):
	"""Override of frappe.desk.notifications.get_open_count, whose counts ignore permissions and whose `items` the
	caller chooses: a restricted DocType gives only the caller's permitted count, and is left out when that is 0."""
	result = notifications.get_open_count(doctype, name, items)
	counts = result.get("count")
	restricted = set(restricted_doctypes())
	if not counts or not restricted:
		return result
	links = frappe.get_meta(doctype).get_dashboard_data()
	counts["external_links_found"] = [
		entry for entry in (
			permitted_external_count(d["doctype"], name, links) if d["doctype"] in restricted else d
			for d in counts.get("external_links_found", [])
		) if entry
	]  # fmt: skip
	counts["internal_links_found"] = [
		entry for entry in (
			permitted_internal_links(d) if d["doctype"] in restricted else d for d in counts.get("internal_links_found", [])
		) if entry
	]  # fmt: skip
	return result


def permitted_external_count(doctype, name, links):
	fieldname = links.get("non_standard_fieldnames", {}).get(doctype, links.get("fieldname"))
	if not fieldname or not frappe.get_meta(doctype).has_field(fieldname) or not frappe.has_permission(doctype, "read"):
		return None
	filters = {fieldname: name, **(notifications.get_dynamic_link_filters(doctype, links, fieldname) or {})}
	count = len(frappe.get_list(doctype, filters=filters, pluck="name", limit=100, order_by=None))
	if not count:
		return None
	open_filters = notifications.get_filters_for(doctype)
	open_count = len(frappe.get_list(doctype, filters={**filters, **open_filters}, pluck="name", limit=100, order_by=None)) if open_filters else 0
	return {"doctype": doctype, "count": count, "open_count": open_count}


def permitted_internal_links(entry):
	names = [n for n in entry.get("names", []) if reference_allows(entry["doctype"], n, "read")]
	return {**entry, "names": names, "count": len(names)} if names else None


# ---- shared ---------------------------------------------------------------------------------


def restricted_attachments(file_url, exclude=None):
	"""(doctype, name) of the restricted records a File row with this URL is attached to."""
	doctypes = restricted_doctypes()
	if not file_url or not doctypes:
		return []
	filters = {"file_url": file_url, "attached_to_doctype": ["in", doctypes], "name": ["!=", exclude or ""]}
	return frappe.get_all("File", filters, ["attached_to_doctype", "attached_to_name"], as_list=True)


def url_readable(file_url, user=None, exclude=None):
	"""True when the URL belongs to no restricted record, or the user reads one of those it belongs to."""
	attachments = restricted_attachments(file_url, exclude)
	return not attachments or any(reference_allows(dt, name, "read", user) for dt, name in attachments)


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
