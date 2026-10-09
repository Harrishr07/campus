"""M01-01 Accreditation Framework lifecycle: the Draft / Published / Retired lock and Clone to new version.

A Published or Retired framework and its nodes are immutable; a change is made on a clone (a new Draft version).
"""

import frappe
from frappe import _

STATUSES = ("Draft", "Published", "Retired")
# parents before children, so a clone can create each node under an existing parent
CREATION_ORDER = ("Criterion", "Extended Profile", "Key Indicator", "Metric", "Sub-Metric")
NODE_FIELDS = (
	"code", "title", "node_type", "description", "answer_type", "choices", "word_limit", "unit", "period",
	"formula", "department_wise", "owner_role",
)  # fmt: skip
SLOT_FIELDS = ("slot_name", "kind", "required")


def status_of(framework):
	"""Status of a framework; frameworks that predate the status field are Drafts."""
	return frappe.db.get_value("Accreditation Framework", framework, "status") or "Draft"


def assert_editable(framework):
	if status_of(framework) != "Draft":
		frappe.throw(
			_("{0} is {1} and cannot be changed. Clone it to a new version to make changes.").format(
				frappe.bold(framework), status_of(framework)
			)
		)


def clone(source, new_name, version):
	"""Copy `source` and all its nodes into the new Draft framework `new_name`; returns its name."""
	if frappe.db.exists("Accreditation Framework", new_name):
		frappe.throw(_("Framework {0} already exists.").format(frappe.bold(new_name)))
	original = frappe.get_doc("Accreditation Framework", source)
	frappe.get_doc(
		{
			"doctype": "Accreditation Framework", "framework_name": new_name, "framework_code": original.framework_code,
			"version": version, "segments": original.segments, "description": original.description,
			"previous_version": source, "status": "Draft",
		}
	).insert()  # fmt: skip
	nodes = [frappe.get_doc("Framework Node", name) for name in frappe.get_all("Framework Node", {"framework": source}, pluck="name")]
	codes = {node.name: node.code for node in nodes}
	nodes.sort(key=lambda node: (CREATION_ORDER.index(node.node_type), node.code))
	for node in nodes:
		values = {field: node.get(field) for field in NODE_FIELDS}
		values["evidence_slots"] = [{field: slot.get(field) for field in SLOT_FIELDS} for slot in node.evidence_slots]
		parent = node.parent_node and f"{new_name}-{codes[node.parent_node]}"
		frappe.get_doc({"doctype": "Framework Node", "framework": new_name, "parent_node": parent, **values}).insert()
	return new_name
