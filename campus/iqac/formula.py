"""M15-01 Framework Node formulas: validation and evaluation in a namespace of data point values only.

The namespace holds exactly the data point keys the formula names, plus round, min and max. Everything else
(frappe, imports, attribute tricks) is unreachable: safe_eval runs without builtins and rejects dunder access.
"""

import ast

import frappe
from frappe import _
from frappe.utils.safe_exec import safe_eval

from campus.iqac.registry import data_point_keys

FUNCTIONS = {"round": round, "min": min, "max": max}


def referenced_keys(formula):
	"""Names a formula uses, other than the whitelisted functions; SyntaxError for an invalid expression."""
	tree = ast.parse(formula.strip(), mode="eval")
	return sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - set(FUNCTIONS))


def validate_formula(formula):
	"""Throw unless `formula` parses, names only registered data points and evaluates over sample values."""
	try:
		keys = referenced_keys(formula)
	except SyntaxError:
		frappe.throw(_("The formula is not a valid expression."))
	unknown = [key for key in keys if key not in data_point_keys()]
	if unknown:
		frappe.throw(_("Unknown data point(s) in the formula: {0}").format(", ".join(unknown)))
	try:
		evaluate(formula, dict.fromkeys(keys, 1))
	except Exception as error:
		frappe.throw(_("The formula cannot be evaluated: {0}").format(str(error) or type(error).__name__))


def evaluate(formula, values):
	"""Value of `formula` over `values` ({key: number}); nothing else is in scope."""
	return safe_eval(formula.strip(), dict(FUNCTIONS), dict(values))
