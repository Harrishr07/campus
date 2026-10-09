"""M15-01 Computing Metric Values: evaluate a node's formula over the data points of a cycle and snapshot it."""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from campus.iqac.formula import ENGINE_VERSION, evaluate, framework_nodes, referenced_keys
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
	done, framework = {}, framework_nodes(doc.framework, lock=False)
	names = []
	for node in nodes:
		try:
			names.append(compute_node(doc, node, done, framework))
		except Exception as error:  # one bad formula must not stop the other metrics
			for unfinished in [n for n, m in done.items() if m is None]:
				del done[unfinished]  # the failed node and the ones it was waiting on
			frappe.log_error(title="Metric not computed", message=f"{node}: {type(error).__name__}: {error}")
	return names


def compute_node(cycle, node, done=None, nodes=None):
	"""Create or refresh the Metric Value of `node` in `cycle` (an Accreditation Cycle doc); returns its name.

	A formula that uses other nodes computes those first; `done` ({node: Metric Value name}) holds the ones already computed and `nodes` is framework_nodes() of the framework."""
	done = {} if done is None else done
	if node in done:
		return done[node]
	node_doc = frappe.get_doc("Framework Node", node)
	if node_doc.framework != cycle.framework or not node_doc.formula:
		frappe.throw(_("{0} has no formula in framework {1}.").format(frappe.bold(node), frappe.bold(cycle.framework)))
	done[node] = None  # a node met again before it finishes is a cycle that validation should have refused
	nodes = nodes or framework_nodes(cycle.framework, lock=False)
	inputs = {key: input_of(cycle, key, nodes, done) for key in referenced_keys(node_doc.formula)}
	try:
		value = evaluate(node_doc.formula, {key: point["value"] for key, point in inputs.items()})
	except ZeroDivisionError:
		value = 0  # no denominator (e.g. nobody appeared): the metric is 0, not an error
	computed_at = now_datetime()
	snapshot = {
		"inputs": inputs, "formula": node_doc.formula, "result": value, "computed_at": str(computed_at),
		"engine_version": ENGINE_VERSION,
	}  # fmt: skip
	metric = metric_value(cycle.name, node_doc)
	metric.update({"value": value, "computed_at": computed_at, "snapshot": json.dumps(snapshot, indent=1)})
	metric.save(ignore_permissions=True)
	done[node] = metric.name
	return metric.name


def input_of(cycle, key, nodes, done):
	"""{"value", "records"} of a data point, or of the Metric Value of a node the formula uses."""
	if key not in nodes:
		return data_point(key, cycle.company, cycle.academic_year)
	code = nodes[key][0]
	name = compute_node(cycle, f"{cycle.framework}-{code}", done, nodes)
	if name is None:
		frappe.throw(_("Node {0} uses itself in its formula.").format(frappe.bold(code)))
	return {"value": frappe.db.get_value("Metric Value", name, "value"), "records": [{"doctype": "Metric Value", "name": name}]}


def metric_value(cycle, node_doc):
	name = f"{cycle}-{node_doc.code}"
	if frappe.db.exists("Metric Value", name):
		return frappe.get_doc("Metric Value", name, for_update=True)
	return frappe.new_doc("Metric Value").update({"cycle": cycle, "node": node_doc.name})
