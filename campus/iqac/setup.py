"""M01-01 / M15-01 IQAC setup: the IQAC Coordinator role and the seeded, published NAAC AQAR framework."""

import inspect

import frappe

from campus.iqac.aqar_seed import PLACEHOLDER, seed_nodes
from campus.iqac.registry import DESCRIPTIONS, REGISTRY, data_point_keys

FRAMEWORK = "NAAC-AQAR-RAF2017"
FRAMEWORK_VALUES = {
	"framework_code": "NAAC-AQAR", "version": "RAF 2017", "segments": "UG\nPG",
	"description": f"NAAC AQAR, Revised Accreditation Framework 2017: structure only, {PLACEHOLDER}.",
}


def ensure_iqac_role():
	if not frappe.db.exists("Role", "IQAC Coordinator"):
		frappe.get_doc({"doctype": "Role", "role_name": "IQAC Coordinator", "desk_access": 1}).insert(
			ignore_permissions=True
		)


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
		doc.update({"key": key, **values})
		doc.save(ignore_permissions=True)
	for stale in set(frappe.get_all("Data Point", pluck="name")) - keys:
		frappe.delete_doc("Data Point", stale, ignore_permissions=True)


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
