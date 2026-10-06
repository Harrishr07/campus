"""M15-01 Computing Metric Values: evaluate a node's formula over the data points of a cycle and snapshot it."""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from campus.iqac.formula import evaluate, referenced_keys
from campus.iqac.registry import data_point

ROLES = ("IQAC Coordinator", "System Manager")


def compute_cycle(cycle):
	"""Compute every Metric node with a formula for the cycle; returns the Metric Value names."""
	doc = frappe.get_doc("Accreditation Cycle", cycle)
	doc.check_permission("write")
	nodes = frappe.get_all(
		"Framework Node",
		{"framework": doc.framework, "node_type": "Metric", "formula": ["is", "set"]},
		pluck="name",
		order_by="code",
	)
	return [compute_node(doc, node) for node in nodes]


def compute_node(cycle, node):
	"""Create or refresh the Metric Value of `node` in `cycle` (an Accreditation Cycle doc); returns its name."""
	node_doc = frappe.get_doc("Framework Node", node)
	if node_doc.framework != cycle.framework or not node_doc.formula:
		frappe.throw(_("{0} has no formula in framework {1}.").format(frappe.bold(node), frappe.bold(cycle.framework)))
	inputs = {
		key: data_point(key, cycle.company, cycle.academic_year) for key in referenced_keys(node_doc.formula)
	}
	try:
		value = evaluate(node_doc.formula, {key: point["value"] for key, point in inputs.items()})
	except ZeroDivisionError:
		value = 0  # no denominator (e.g. nobody appeared): the metric is 0, not an error
	computed_at = now_datetime()
	snapshot = {"inputs": inputs, "formula": node_doc.formula, "computed_at": str(computed_at)}
	metric = metric_value(cycle.name, node_doc)
	metric.update({"value": value, "computed_at": computed_at, "snapshot": json.dumps(snapshot, indent=1)})
	metric.save(ignore_permissions=True)
	return metric.name


def metric_value(cycle, node_doc):
	name = f"{cycle}-{node_doc.code}"
	if frappe.db.exists("Metric Value", name):
		return frappe.get_doc("Metric Value", name, for_update=True)
	return frappe.new_doc("Metric Value").update({"cycle": cycle, "node": node_doc.name})
