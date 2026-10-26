"""M01-01, principle 6 Evidence registry: what an Evidence currently points at, which of it the public may get, and the
filled / missing state of a node's evidence slots per cycle.

Safety rule for the public pages: a file is served only when its Evidence is public AND the file is public (a /files/ path with
a public File record). The file of an Evidence linked to a source record is always read from the source's Attach field, so a
replaced source file changes what the same public URL gives; if that file is gone or private, nothing is served.
"""

import re

import frappe
from frappe import _

from campus.iqac.access import ROLES, has_role

EVIDENCE_FIELDS = ["name", "title", "slug", "evidence_type", "academic_year", "description", "kind", "file", "url",
	"source_doctype", "source_name", "source_field", "is_public", "company"]  # fmt: skip
ATTACH_TYPES = ("Attach", "Attach Image")
WEB_URL = re.compile(r"^https?://[^\s<>\"']+$", re.IGNORECASE)


def unique_slug(title):
	base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:80] or "evidence"
	slug, count = base, 1
	while frappe.db.exists("Evidence", slug):
		count += 1
		slug = f"{base}-{count}"
	return slug


def is_web_url(url):
	return bool(url and WEB_URL.fullmatch(url))


def is_public_file(file_url):
	"""A /files/ path (no traversal) of a File record that is not private."""
	if not file_url or not file_url.startswith("/files/") or ".." in file_url or "\\" in file_url:
		return False
	if frappe.db.exists("File", {"file_url": file_url, "is_private": 1}):
		return False
	return bool(frappe.db.exists("File", {"file_url": file_url, "is_private": 0}))


def current_file(doc):
	"""The file an Evidence points at now: the source field's current value when linked to a source record, else its own file."""
	if doc.get("source_field"):
		if not (
			doc.get("source_doctype")
			and doc.get("source_name")
			and frappe.db.exists(doc.source_doctype, doc.source_name)
		):
			return None
		return frappe.db.get_value(doc.source_doctype, doc.source_name, doc.source_field) or None
	return doc.get("file") or None


def current_location(doc):
	"""File path or web address now behind the Evidence (None when missing)."""
	return doc.get("url") or None if doc.get("kind") == "URL" else current_file(doc)


def public_target(name):
	"""Where /disclosure/<name> goes, or None. None for unknown, non-public, private-file and malformed alike."""
	doc = frappe.db.get_value("Evidence", name, EVIDENCE_FIELDS, as_dict=True) if name else None
	if not doc or not doc.is_public:
		return None
	if doc.kind == "URL":
		return doc.url if is_web_url(doc.url) else None
	file_url = current_file(doc)
	return file_url if is_public_file(file_url) else None


def public_listing():
	"""[(college, academic year, [(type, [Evidence rows])])] of what the public may get: by college, then newest year first."""
	rows = frappe.get_all("Evidence", {"is_public": 1}, EVIDENCE_FIELDS, order_by="title")
	rows = [row for row in rows if public_target(row.name)]
	years = {y.name: y.year_start_date for y in frappe.get_all("Academic Year", ["name", "year_start_date"])}
	types = frappe.get_meta("Evidence").get_field("evidence_type").options.split("\n")
	groups = []
	for company in sorted({row.company or "" for row in rows}):
		mine = [row for row in rows if (row.company or "") == company]
		for year in sorted(
			{row.academic_year for row in mine}, key=lambda y: str(years.get(y) or ""), reverse=True
		):
			by_type = [
				(kind, [r for r in mine if r.academic_year == year and r.evidence_type == kind])
				for kind in types
			]
			groups.append((company, year, [(kind, found) for kind, found in by_type if found]))
	return groups


def check_may_publish():
	if not has_role(frappe.session.user, ROLES):
		frappe.throw(
			_("Only an IQAC Coordinator or System Manager can make evidence public."), frappe.PermissionError
		)


def slot_status(cycle, node=None):
	"""One row per evidence slot of `node` (or of every node of the cycle's framework): filled when an Evidence of the cycle's
	college and academic year names the slot, has the slot's kind and currently has a file or address."""
	scope = frappe.db.get_value(
		"Accreditation Cycle", cycle, ["framework", "company", "academic_year"], as_dict=True
	)
	nodes = [node] if node else frappe.get_all("Framework Node", {"framework": scope.framework}, pluck="name")
	slots = frappe.get_all(
		"Framework Node Evidence Slot", {"parenttype": "Framework Node", "parent": ["in", nodes or [""]]},
		["parent as node", "slot_name", "kind", "required"], order_by="parent, idx",
	)  # fmt: skip
	found = filled_by(scope, nodes)
	return [
		frappe._dict(
			**slot,
			evidence=found.get((slot.node, slot.slot_name, slot.kind), []),
			filled=bool(found.get((slot.node, slot.slot_name, slot.kind))),
		)
		for slot in slots
	]


def filled_by(scope, nodes):
	"""{(node, slot name, kind): [Evidence names]} for evidence of the college and year that currently has content."""
	docs = {
		doc.name: doc
		for doc in frappe.get_all(
			"Evidence", {"company": scope.company, "academic_year": scope.academic_year}, EVIDENCE_FIELDS
		)
	}
	if not docs:
		return {}
	found = {}
	for row in frappe.get_all(
		"Evidence Node", {"parenttype": "Evidence", "parent": ["in", list(docs)], "node": ["in", nodes or [""]]}, ["parent", "node", "slot_name"]
	):  # fmt: skip
		doc = docs[row.parent]
		if current_location(doc):
			found.setdefault((row.node, row.slot_name, doc.kind), []).append(doc.name)
	return found


def source_file_field(doctype):
	"""The file field Campus Settings > Evidence Sources lists for `doctype` ("" for none); throws when it is not listed."""
	field = frappe.db.get_value(
		"Evidence Source Doctype", {"parent": "Campus Settings", "document_type": doctype}, "file_field"
	)
	if field is None:
		frappe.throw(
			_("{0} is not listed under Evidence Sources in Campus Settings.").format(frappe.bold(doctype))
		)
	return field


def attach_as_evidence(
	doctype, name, title, evidence_type, academic_year, nodes=None, is_public=0, file=None, url=None
):
	"""Make an Evidence from any record whose document type is listed in Campus Settings > Evidence Sources; returns its name."""
	source = source_file_field(doctype)
	frappe.has_permission(doctype, "read", name, throw=True)
	values = {
		"doctype": "Evidence", "title": title, "evidence_type": evidence_type, "academic_year": academic_year,
		"company": source_company(doctype, name), "source_doctype": doctype, "source_name": name,
		"is_public": int(frappe.parse_json(is_public) or 0), "nodes": frappe.parse_json(nodes) or [],
	}  # fmt: skip
	if source:
		values.update({"kind": "File", "source_field": source})
	elif url:
		values.update({"kind": "URL", "url": url})
	else:
		values.update({"kind": "File", "file": file})
	return frappe.get_doc(values).insert().name


def source_company(doctype, name):
	meta = frappe.get_meta(doctype)
	if doctype == "Company":
		return name
	for field in ("company", "oc_company"):
		if meta.has_field(field) and frappe.db.get_value(doctype, name, field):
			return frappe.db.get_value(doctype, name, field)
	company = frappe.db.get_single_value("Campus Settings", "default_company")
	if not company:
		frappe.throw(
			_("{0} has no company; set a Default Company in Campus Settings.").format(frappe.bold(name))
		)
	return company
