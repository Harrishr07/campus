"""M01-02 / M01-03 Computing Metric Values: evaluate a node's formula over the data points of a cycle and snapshot it.

A department-wise node is computed for the college and for each department that has programmes. Computing never
overwrites a Verified or Locked value (it records that the source changed instead, see campus.iqac.metric_values) and is
refused once the cycle is approved. `compute_all` runs the nodes as a resumable bulk run.
"""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from campus.campus_platform.bulk import live_run, run_bulk
from campus.iqac.access import ROLES  # noqa: F401  (re-exported: campus.iqac.api checks it)
from campus.iqac.cycle import assert_open
from campus.iqac.formula import ENGINE_VERSION, evaluate, framework_nodes, referenced_keys
from campus.iqac.metric_values import FROZEN, note_source_change
from campus.iqac.registry import data_point

RUN_TYPE = "IQAC Compute All"
HANDLER = "campus.iqac.compute.compute_item"
CHUNK = 10


def formula_nodes(framework):
	return frappe.get_all(
		"Framework Node", {"framework": framework, "node_type": "Metric", "formula": ["is", "set"]}, pluck="name", order_by="code"
	)


def open_cycle(cycle):
	"""The Accreditation Cycle doc the user may compute, throwing once its values are locked."""
	doc = frappe.get_doc("Accreditation Cycle", cycle)
	assert_open(doc)
	doc.check_permission("write")
	return doc


def compute_cycle(cycle):
	"""Compute every Metric node with a formula for the cycle; returns the Metric Value names."""
	doc = open_cycle(cycle)
	done, framework = {}, framework_nodes(doc.framework, lock=False)
	names = []
	for node in formula_nodes(doc.framework):
		try:
			names.extend(compute_node_everywhere(doc, node, done, framework))
		except Exception as error:  # one bad formula must not stop the other metrics
			for unfinished in [key for key, name in done.items() if name is None]:
				del done[unfinished]  # the failed node and the ones it was waiting on
			frappe.log_error(title="Metric not computed", message=f"{node}: {type(error).__name__}: {error}")
	return names


def compute_all(cycle):
	"""Queue the computation of every formula node as a bulk run; returns the Bulk Run name (a live one is reused)."""
	frappe.only_for(ROLES)
	doc = open_cycle(cycle)
	frappe.db.get_value("Accreditation Cycle", cycle, "name", for_update=True)  # one start at a time
	running = live_run(RUN_TYPE, cycle=cycle)
	if running:
		return running
	return run_bulk(RUN_TYPE, formula_nodes(doc.framework), HANDLER, chunk=CHUNK, parameters={"cycle": cycle})


def compute_item(node, run):
	"""Bulk handler: compute one node (and its department rows) for the run's cycle. DB-only, no commit."""
	cycle = frappe.get_doc("Accreditation Cycle", run.get_parameters()["cycle"])
	assert_open(cycle)
	compute_node_everywhere(cycle, node, {}, framework_nodes(cycle.framework, lock=False))


def compute_node_everywhere(cycle, node, done, nodes):
	"""The college's Metric Value of `node`, and a row per programme department when the node is department-wise."""
	names = [compute_node(cycle, node, done, nodes)]
	if frappe.db.get_value("Framework Node", node, "department_wise"):
		names += [compute_node(cycle, node, done, nodes, department) for department in programme_departments(cycle.company)]
	return names


def programme_departments(company):
	"""Departments that own programmes of the college."""
	return frappe.get_all(
		"Program", {"oc_company": company, "department": ["is", "set"]}, pluck="department", distinct=True, order_by="department"
	)


def compute_node(cycle, node, done=None, nodes=None, department=None):
	"""Create or refresh the Metric Value of `node` in `cycle` (an Accreditation Cycle doc); returns its name.

	A formula that uses other nodes computes those first (for the same department); `done` ({(node, department): name})
	holds the ones already computed and `nodes` is framework_nodes() of the framework."""
	done = {} if done is None else done
	node_doc = frappe.get_doc("Framework Node", node)
	department = department if node_doc.department_wise else None
	if (node, department) in done:
		return done[(node, department)]
	if node_doc.framework != cycle.framework or not node_doc.formula:
		frappe.throw(_("{0} has no formula in framework {1}.").format(frappe.bold(node), frappe.bold(cycle.framework)))
	done[(node, department)] = None  # a node met again before it finishes is a cycle that validation should have refused
	nodes = nodes or framework_nodes(cycle.framework, lock=False)
	inputs = {key: input_of(cycle, key, nodes, done, department) for key in referenced_keys(node_doc.formula)}
	try:
		value = evaluate(node_doc.formula, {key: point["value"] for key, point in inputs.items()})
	except ZeroDivisionError:
		value = 0  # no denominator (e.g. nobody appeared): the metric is 0, not an error
	computed_at = now_datetime()
	snapshot = {
		"inputs": inputs, "formula": node_doc.formula, "result": value, "computed_at": str(computed_at),
		"engine_version": ENGINE_VERSION,
	}  # fmt: skip
	metric = metric_value(cycle.name, node_doc, department)
	if metric.status in FROZEN:
		note_source_change(metric, value, inputs)
	else:
		metric.update(
			{"computed_value": value, "computed_at": computed_at, "snapshot": json.dumps(snapshot, indent=1), "source_changed": 0, "recomputed_value": None}
		)
		metric.flags.engine_write = True
		metric.save(ignore_permissions=True)
	done[(node, department)] = metric.name
	return metric.name


def input_of(cycle, key, nodes, done, department=None):
	"""{"value", "records"} of a data point, or of the Metric Value of a node the formula uses."""
	if key not in nodes:
		return data_point(key, cycle.company, cycle.academic_year, department)
	code = nodes[key][0]
	name = compute_node(cycle, f"{cycle.framework}-{code}", done, nodes, department)
	if name is None:
		frappe.throw(_("Node {0} uses itself in its formula.").format(frappe.bold(code)))
	return {"value": frappe.db.get_value("Metric Value", name, "value"), "records": [{"doctype": "Metric Value", "name": name}]}


def metric_value(cycle, node_doc, department=None):
	name = f"{cycle}-{node_doc.code}" + (f"-{department}" if department else "")
	if frappe.db.exists("Metric Value", name):
		return frappe.get_doc("Metric Value", name, for_update=True)
	return frappe.new_doc("Metric Value").update({"cycle": cycle, "node": node_doc.name, "department": department})
