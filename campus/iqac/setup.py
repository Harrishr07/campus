"""M01-01 / M15-01 IQAC setup: the IQAC Coordinator role and the seeded, published NAAC AQAR framework."""

import inspect

import frappe

from campus.iqac.access import OWNER_ROLE
from campus.iqac.aqar_seed import PLACEHOLDER, seed_nodes
from campus.iqac.formula import referenced_keys
from campus.iqac.registry import DESCRIPTIONS, REGISTRY, data_point_keys

FRAMEWORK = "NAAC-AQAR-RAF2017"
FRAMEWORK_VALUES = {
	"framework_code": "NAAC-AQAR", "version": "RAF 2017", "segments": "UG\nPG",
	"description": f"NAAC AQAR, Revised Accreditation Framework 2017: structure only, {PLACEHOLDER}.",
}


def ensure_iqac_role():
	for role in ("IQAC Coordinator", OWNER_ROLE):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def seed_iqac_policies():
	"""Approval policies for a cycle (the Principal of the college) and a Metric Override (its IQAC Coordinator), unless the
	college has its own. Skipped while the position is not seeded."""
	for document_type, position, title in (
		("Accreditation Cycle", "PRINCIPAL", "Principal"),
		("Metric Override", "IQAC-COORDINATOR", "IQAC Coordinator"),
	):
		if frappe.db.exists("Approval Policy", {"document_type": document_type}) or not frappe.db.exists("Position", position):
			continue
		frappe.get_doc(
			{
				"doctype": "Approval Policy", "policy_name": f"{document_type} approval", "document_type": document_type,
				"levels": [{"approver_type": "Position", "approver": position, "scope_field": "company", "title": title, "sla_hours": 48}],
			}
		).insert(ignore_permissions=True)  # fmt: skip


def sync_data_points():
	"""Make the Data Point records mirror the `@campus_metric` registry: add, refresh and remove (M01-02)."""
	keys = data_point_keys()
	for key in sorted(keys):
		function = REGISTRY[key]
		values = {
			"module": DESCRIPTIONS[key]["module"] or "IQAC",
			"description": DESCRIPTIONS[key]["description"] or key.replace("_", " ").capitalize(),
			"parameters": ", ".join(inspect.signature(function).parameters),
			"function": f"{function.__module__}.{function.__name__}",
		}
		doc = frappe.get_doc("Data Point", key) if frappe.db.exists("Data Point", key) else frappe.new_doc("Data Point")
		doc.update({"key": key, "registered": 1, **values})
		doc.save(ignore_permissions=True)
	used = formula_keys()
	for stale in set(frappe.get_all("Data Point", pluck="name")) - keys:
		if stale in used:  # a formula still names it: keep the record, flagged, and say so
			frappe.db.set_value("Data Point", stale, "registered", 0)
			frappe.log_error(
				title="Unregistered data point still used", message=f"Data point {stale} is used by a Framework Node formula but no longer registered."
			)
		else:
			frappe.delete_doc("Data Point", stale, ignore_permissions=True)


def formula_keys():
	"""Every name used by a Framework Node formula."""
	used = set()
	for formula in frappe.get_all("Framework Node", {"formula": ["is", "set"]}, pluck="formula"):
		try:
			used.update(referenced_keys(formula))
		except (SyntaxError, ValueError, RecursionError, MemoryError):
			continue
	return used


def seed_framework():
	"""Create the NAAC AQAR framework with its nodes and publish it; a published framework is left alone.

	A Draft left by an earlier install gets its missing nodes added and its blank fields filled, never overwritten."""
	if frappe.db.exists("Accreditation Framework", FRAMEWORK):
		framework = frappe.get_doc("Accreditation Framework", FRAMEWORK)
	else:
		framework = frappe.get_doc({"doctype": "Accreditation Framework", "framework_name": FRAMEWORK}).insert(
			ignore_permissions=True
		)
	if framework.status in ("Published", "Retired"):
		return
	fill_blanks(framework, FRAMEWORK_VALUES)
	for spec in seed_nodes():
		seed_node(spec)
	framework.status = "Published"
	framework.save(ignore_permissions=True)


def seed_node(spec):
	name = f"{FRAMEWORK}-{spec['code']}"
	values = {**spec, "parent_node": spec["parent"] and f"{FRAMEWORK}-{spec['parent']}"}
	del values["parent"]
	if not frappe.db.exists("Framework Node", name):
		frappe.get_doc({"doctype": "Framework Node", "framework": FRAMEWORK, **values}).insert(ignore_permissions=True)
		return
	node = frappe.get_doc("Framework Node", name)
	if fill_blanks(node, values):
		node.save(ignore_permissions=True)


def fill_blanks(doc, values):
	"""Set the fields of `doc` that are still empty; True when something changed."""
	blank = {field: value for field, value in values.items() if value and not doc.get(field)}
	doc.update(blank)
	return bool(blank)


EVIDENCE_SOURCES = ("Body Meeting", "Circular", "Faculty Achievement", "Sanction", "Feedback Campaign", "Placement Drive")
EVIDENCE_FILE_FIELDS = {"Faculty Achievement": "evidence", "Feedback Campaign": "action_taken_report"}


def seed_evidence_sources():
	"""List the document types that offer Attach as Evidence (those that exist yet) which are not listed; the college edits the list."""
	settings = frappe.get_doc("Campus Settings")
	listed = {row.document_type for row in settings.evidence_sources}
	missing = [d for d in EVIDENCE_SOURCES if d not in listed and frappe.db.exists("DocType", d)]
	for document_type in missing:
		settings.append("evidence_sources", {"document_type": document_type, "file_field": EVIDENCE_FILE_FIELDS.get(document_type)})
	if missing:
		settings.flags.ignore_permissions = True
		settings.save()
