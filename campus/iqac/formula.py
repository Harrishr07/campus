"""M01-02 / M15-01 Framework Node formulas: validation, evaluation and node-reference cycle detection.

A formula is an arithmetic expression over data point keys and other nodes of its framework (a node's code
`2.6.3` is written `n_2_6_3`). It is checked against an AST whitelist (numbers, names, arithmetic, comparisons,
and/or, conditional expressions and calls of round / min / max) and then run by frappe.safe_eval in a namespace
of exactly the values it names, so frappe, imports, attribute walks, lambdas and comprehensions are unreachable.
Power and shifts are refused: `9 ** 9 ** 9` would hang a worker.
"""

import ast
import re

import frappe
from frappe import _
from frappe.utils.safe_exec import safe_eval

from campus.iqac.registry import data_point_keys

ENGINE_VERSION = "1"
FUNCTIONS = {"round": round, "min": min, "max": max}
ALLOWED_NODES = (
	ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call, ast.Name, ast.Constant,
	ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.UAdd, ast.USub, ast.And, ast.Or, ast.Not,
	ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)  # fmt: skip


def node_identifier(code):
	"""The name a formula uses for the node with `code`."""
	return "n_" + re.sub(r"\W", "_", code)


def parse(formula):
	"""AST of `formula`; SyntaxError when it is not a plain expression of whitelisted constructs."""
	tree = ast.parse(formula.strip(), mode="eval")
	for item in ast.walk(tree):
		if not isinstance(item, ALLOWED_NODES) or not allowed(item):
			raise SyntaxError(f"Operation not allowed: {type(item).__name__}")
	return tree


def allowed(item):
	if isinstance(item, ast.Constant):
		return isinstance(item.value, int | float) and not isinstance(item.value, bool)
	if isinstance(item, ast.Call):
		return isinstance(item.func, ast.Name) and item.func.id in FUNCTIONS and not item.keywords
	return True


def referenced_keys(formula):
	"""Names a formula uses, other than the whitelisted functions; SyntaxError for an invalid expression."""
	tree = parse(formula)
	return sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - set(FUNCTIONS))


def evaluate(formula, values):
	"""Value of `formula` over `values` ({name: number}); nothing else is in scope."""
	parse(formula)
	return safe_eval(formula.strip(), dict(FUNCTIONS), dict(values))


def validate_formula(formula, framework=None, code=None, check_nodes=True):
	"""Throw unless `formula` is valid: only registered data points and, with `framework`, formula nodes of it.

	`code` is the node being saved; a reference chain that comes back to it is a cycle."""
	try:
		keys = referenced_keys(formula)
	except SyntaxError:
		frappe.throw(_("The formula is not a valid expression."))
	points = data_point_keys()
	nodes = framework_nodes(framework) if framework else {}
	if code:
		nodes[node_identifier(code)] = (code, formula)  # this node, as it is about to be saved
	later = () if check_nodes else tuple(key for key in keys if key.startswith("n_"))  # a clone: nodes created later
	unknown = [key for key in keys if key not in points and key not in nodes and key not in later]
	if unknown:
		frappe.throw(_("Unknown data point(s) or node(s) in the formula: {0}").format(", ".join(unknown)))
	if check_nodes:
		check_node_references(framework, code, keys, nodes)
	try:
		evaluate(formula, dict.fromkeys(keys, 1))
	except Exception as error:
		frappe.throw(_("The formula cannot be evaluated: {0}").format(str(error) or type(error).__name__))


def framework_nodes(framework, lock=True):
	"""{identifier: (code, formula)} of the nodes of `framework`; `lock` reads under a row lock so concurrent saves see each other."""
	table = frappe.qb.DocType("Framework Node")
	query = frappe.qb.from_(table).select(table.code, table.formula).where(table.framework == framework)
	rows = (query.for_update() if lock else query).run(as_dict=True)
	return {node_identifier(row.code): (row.code, row.formula) for row in rows}


def check_node_references(framework, code, keys, nodes):
	for key in keys:
		if key in nodes and not nodes[key][1]:
			frappe.throw(_("Node {0} has no formula, so a formula cannot use it.").format(frappe.bold(nodes[key][0])))
	graph = {nodes[key][0]: node_references(nodes[key][1], nodes) for key in nodes if nodes[key][1]}
	if code:
		graph[code] = {nodes[key][0] for key in keys if key in nodes}
		path = cycle_through(graph, code)
		if path:
			frappe.throw(_("The formula makes a cycle between nodes: {0}").format(" -> ".join(path)))


def node_references(formula, nodes):
	return {nodes[key][0] for key in referenced_keys(formula) if key in nodes}


def cycle_through(graph, start):
	"""Path `start -> ... -> start` along `graph` ({code: {codes it uses}}), or None."""
	stack = [(start, [start])]
	seen = set()
	while stack:
		code, path = stack.pop()
		for used in sorted(graph.get(code, ())):
			if used == start:
				return [*path, start]
			if used not in seen:
				seen.add(used)
				stack.append((used, [*path, used]))
	return None


def dependents(framework, code):
	"""Codes of the nodes whose formula uses the node `code`."""
	nodes = framework_nodes(framework)
	return sorted(
		other for other, formula in nodes.values() if formula and code in node_references(formula, nodes)
	)
