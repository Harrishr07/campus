"""M01-03 Cycle Readiness: per criterion of a cycle, how much is answered, what evidence is missing, which rules fail, and who owns it.

Limited to cycles the user may read (Company User Permissions). Failures are computed afresh (campus.iqac.validation).
"""

import frappe
from frappe import _

from campus.iqac import evidence, validation
from campus.iqac.cycle import ANSWER_NODES

EXTENDED_PROFILE = "Extended Profile"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.get_doc("Accreditation Cycle", filters.cycle).check_permission("read")
	return columns(), data(filters.cycle)


def columns():
	return [
		{"fieldname": "criterion", "label": _("Criterion"), "fieldtype": "Link", "options": "Framework Node", "width": 160},
		{"fieldname": "title", "label": _("Title"), "fieldtype": "Data", "width": 220},
		{"fieldname": "owner", "label": _("Owner"), "fieldtype": "Data", "width": 200},
		{"fieldname": "answerable", "label": _("Answerable"), "fieldtype": "Int", "width": 90},
		{"fieldname": "answered", "label": _("Answered"), "fieldtype": "Int", "width": 90},
		{"fieldname": "completion", "label": _("Completion %"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "missing_evidence", "label": _("Missing Evidence"), "fieldtype": "Int", "width": 120},
		{"fieldname": "blocking", "label": _("Blocking Failures"), "fieldtype": "Int", "width": 120},
		{"fieldname": "warnings", "label": _("Warnings"), "fieldtype": "Int", "width": 90},
	]  # fmt: skip


def data(cycle):
	framework = frappe.db.get_value("Accreditation Cycle", cycle, "framework")
	nodes = {
		n.name: n
		for n in frappe.get_all(
			"Framework Node",
			{"framework": framework},
			["name", "title", "parent_node", "node_type", "answer_type"],
		)
	}
	root = lambda name: root_of(nodes, name)  # noqa: E731
	rows = {n.name: new_row(n.name, n.title) for n in nodes.values() if n.node_type == "Criterion"}
	rows[EXTENDED_PROFILE] = new_row(None, _(EXTENDED_PROFILE))
	key = lambda name: root(name) if root(name) in rows else EXTENDED_PROFILE  # noqa: E731
	answered = set(frappe.get_all("Metric Value", {"cycle": cycle, "answered": 1}, pluck="node"))
	for node in nodes.values():
		if node.node_type in ANSWER_NODES and node.answer_type:
			row = rows[key(node.name)]
			row["answerable"] += 1
			row["answered"] += node.name in answered
	for criterion, owners in owners_of(cycle).items():
		if criterion in rows:
			rows[criterion]["owner"] = ", ".join(owners)
	add_failures(cycle, rows, key)
	for row in rows.values():
		row["completion"] = round(100 * row["answered"] / row["answerable"], 1) if row["answerable"] else 0
	return [row for row in rows.values() if row["criterion"] or row["answerable"]]


def new_row(criterion, title):
	return {"criterion": criterion, "title": title, "owner": "", "answerable": 0, "answered": 0, "completion": 0,
		"missing_evidence": 0, "blocking": 0, "warnings": 0}  # fmt: skip


def root_of(nodes, name):
	while nodes[name].parent_node:
		name = nodes[name].parent_node
	return name


def owners_of(cycle):
	owners = {}
	for row in frappe.get_all(
		"Accreditation Cycle Owner",
		{"parent": cycle, "parenttype": "Accreditation Cycle"},
		["criterion", "user"],
		order_by="idx",
	):
		owners.setdefault(row.criterion, []).append(row.user)
	return owners


def add_failures(cycle, rows, key):
	"""Rule failures per branch; missing evidence is the unfilled slots named by a rule or marked Required on the node."""
	missing = set()
	for failure in validation.evaluate(cycle):
		row = rows[key(failure.node)]
		row["blocking" if failure.severity == "Blocking" else "warnings"] += 1
		if failure.rule_type == "Required Evidence":
			missing.add((failure.node, failure.slot_name))
	missing |= {(s.node, s.slot_name) for s in evidence.slot_status(cycle) if s.required and not s.filled}
	for node, _slot in missing:
		rows[key(node)]["missing_evidence"] += 1
