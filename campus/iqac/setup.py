"""M01-01 / M15-01 IQAC setup: the IQAC Coordinator role and the seeded, published NAAC AQAR framework."""

import frappe

from campus.iqac.aqar_seed import PLACEHOLDER, seed_nodes

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
