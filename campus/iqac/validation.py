"""M01-03 Pre-validation: check an Accreditation Cycle against the Validation Rules of its framework.

The rules are records; this module only knows how to evaluate each rule type. `evaluate` is always computed afresh from the
cycle's Metric Values and evidence; `run` stores the outcome as a Validation Run; `gate` is the check made when a cycle moves
from Validating to IQAC Review: blocking failures stop it, warnings are allowed with a comment.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from campus.iqac import evidence
from campus.iqac.access import ROLES

OPERATORS = {
	"<=": lambda a, b: a <= b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "=": lambda a, b: a == b,
}  # fmt: skip
RULE_FIELDS = ["name", "rule_type", "severity", "node", "slot_name", "compare_node", "operator", "limit", "minimum", "maximum", "message"]
SHOWN = 8


def holds(left, operator, right):
	"""True when `left <operator> right`."""
	return OPERATORS[operator](left, right)


def outside_range(value, minimum, maximum):
	"""True when `value` is below `minimum` or above `maximum`; an unset (None) bound is not checked."""
	return (minimum is not None and value < minimum) or (maximum is not None and value > maximum)


def range_text(minimum, maximum):
	"""The bounds of a Range rule in words; an unset bound is open-ended."""
	if minimum in (None, ""):
		return _("at most {0}").format(maximum)
	if maximum in (None, ""):
		return _("{0} or more").format(minimum)
	return _("{0} to {1}").format(minimum, maximum)


def bound(text):
	"""A Range rule's bound (kept as text) as a number; None when blank."""
	return None if text in (None, "") else flt(text)


class Context:
	"""What the rules look at: the cycle's answered Metric Values per node, and the evidence slots of a node (read once)."""

	def __init__(self, cycle):
		self.cycle = cycle
		self.values = defaultdict(list)
		for row in frappe.get_all(
			"Metric Value", {"cycle": cycle}, ["node", "department", "value", "answered", "word_count"], order_by="name"
		):
			self.values[row.node].append(row)
		self.nodes = {}
		self.slots = {}

	def answered(self, node):
		return [row for row in self.values[node] if row.answered]

	def total(self, node):
		return sum(flt(row.value) for row in self.answered(node))

	def node_limit(self, node):
		if node not in self.nodes:
			self.nodes[node] = frappe.db.get_value("Framework Node", node, "word_limit")
		return self.nodes[node]

	def slot_rows(self, node):
		if node not in self.slots:
			self.slots[node] = evidence.slot_status(self.cycle, node)
		return self.slots[node]


def failure(rule, detail, department=None, slot_name=None):
	return frappe._dict(
		rule=rule.name, rule_type=rule.rule_type, severity=rule.severity, node=rule.node, department=department,
		message=rule.message, detail=detail, slot_name=slot_name,
	)  # fmt: skip


def check_required_evidence(rule, ctx):
	slots = ctx.slot_rows(rule.node)
	wanted = [s for s in slots if (s.slot_name == rule.slot_name if rule.slot_name else s.required)]
	if rule.slot_name and not wanted:
		return [failure(rule, _("{0} has no evidence slot {1}.").format(rule.node, rule.slot_name), slot_name=rule.slot_name)]
	return [failure(rule, _("No evidence for {0}.").format(s.slot_name), slot_name=s.slot_name) for s in wanted if not s.filled]


def check_word_limit(rule, ctx):
	limit = rule.limit or ctx.node_limit(rule.node)
	return [
		failure(rule, _("{0} words; the limit is {1}.").format(row.word_count, limit), row.department)
		for row in ctx.answered(rule.node) if row.word_count > limit
	]  # fmt: skip


def check_comparison(rule, ctx):
	"""Each side is the sum of the node's answered Metric Values (the college row and any department rows)."""
	if not (ctx.answered(rule.node) and ctx.answered(rule.compare_node)):
		return []  # an unanswered side is a Non-empty matter, not a comparison failure
	left, right = ctx.total(rule.node), ctx.total(rule.compare_node)
	if holds(left, rule.operator, right):
		return []
	return [failure(rule, _("{0} is not {1} {2} ({3}).").format(left, rule.operator, right, rule.compare_node))]


def check_range(rule, ctx):
	return [
		failure(rule, _("{0} is outside {1}.").format(row.value, range_text(rule.minimum, rule.maximum)), row.department)
		for row in ctx.answered(rule.node) if outside_range(flt(row.value), bound(rule.minimum), bound(rule.maximum))
	]  # fmt: skip


def check_non_empty(rule, ctx):
	return [] if ctx.answered(rule.node) else [failure(rule, _("{0} is not answered.").format(rule.node))]


CHECKS = {
	"Required Evidence": check_required_evidence, "Word Limit": check_word_limit, "Comparison": check_comparison,
	"Range": check_range, "Non-empty": check_non_empty,
}  # fmt: skip


def evaluate(cycle):
	"""Failures of the enabled rules of the cycle's framework, as dicts (rule, rule_type, severity, node, department, message, detail)."""
	framework = frappe.db.get_value("Accreditation Cycle", cycle, "framework")
	rules = frappe.get_all("Validation Rule", {"framework": framework, "enabled": 1}, RULE_FIELDS, order_by="name")
	ctx = Context(cycle)
	return [found for rule in rules for found in CHECKS[rule.rule_type](rule, ctx)]


def counts(failures):
	return {
		"blocking": sum(f.severity == "Blocking" for f in failures),
		"warnings": sum(f.severity == "Warning" for f in failures),
	}


def readable(cycle):
	"""Name of a cycle the caller, an IQAC role holder, may read (its company permitted)."""
	frappe.only_for(ROLES)
	frappe.get_doc("Accreditation Cycle", cycle).check_permission("read")
	return cycle


def run(cycle):
	"""Check the cycle now and store a Validation Run; returns its name."""
	failures = evaluate(readable(cycle))
	return frappe.get_doc(
		{
			"doctype": "Validation Run", "cycle": cycle, "run_on": now_datetime(), "run_by": frappe.session.user, **counts(failures),
			"results": [{k: f[k] for k in ("rule", "rule_type", "severity", "node", "department", "message", "detail")} for f in failures],
		}
	).insert(ignore_permissions=True).name  # fmt: skip


def summary(cycle):
	return counts(evaluate(readable(cycle)))


def gate(cycle, comment=None):
	"""Called when `cycle` (an Accreditation Cycle doc) leaves Validating: blocking failures stop it; warnings need `comment`."""
	failures = evaluate(cycle.name)
	blocking = [f for f in failures if f.severity == "Blocking"]
	warnings = [f for f in failures if f.severity == "Warning"]
	if blocking:
		frappe.throw(
			_("{0} has {1} blocking validation failure(s): {2}").format(frappe.bold(cycle.name), len(blocking), listing(blocking)),
			title=_("Validation Failed"),
		)
	if not warnings:
		return
	if not (comment or "").strip():
		frappe.throw(
			_("{0} has {1} validation warning(s): {2}. Add a comment to move on.").format(frappe.bold(cycle.name), len(warnings), listing(warnings)),
			title=_("Comment Required"),
		)
	cycle.add_comment("Comment", _("Moved to IQAC Review with {0} validation warning(s): {1}").format(len(warnings), comment.strip()))


def listing(failures):
	shown = "; ".join(f"{f.message} ({f.node.rsplit('-', 1)[-1]})" for f in failures[:SHOWN])
	return shown + (_(" and {0} more").format(len(failures) - SHOWN) if len(failures) > SHOWN else "")
