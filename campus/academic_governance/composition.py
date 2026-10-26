"""M02-01 Body composition: who is in office on a date, and whether the members meet the Body Type's rule.

Pure functions over plain rows (dicts or documents) so the rule logic is testable without a database. A member
is in office from From through To inclusive; an empty To is an open term. Members whose term has ended are
excluded from every count, so they never count towards quorum.
"""

import frappe
from frappe import _
from frappe.utils import formatdate, getdate


def in_office(member, on_date):
	on_date = getdate(on_date)
	if not member.from_date or getdate(member.from_date) > on_date:
		return False
	return not member.to_date or getdate(member.to_date) >= on_date


def members_in_office(members, on_date):
	return [m for m in members if in_office(m, on_date)]


def count_by_category(members, on_date):
	counts = {}
	for member in members_in_office(members, on_date):
		counts[member.category] = counts.get(member.category, 0) + 1
	return counts


def composition_shortfalls(rules, members, on_date):
	"""One record per rule the members in office do not meet: category, minimum, maximum, actual, rule, message."""
	counts = count_by_category(members, on_date)
	shortfalls = []
	for rule in rules:
		actual = counts.get(rule.category, 0)
		minimum, maximum = rule.minimum_count or 0, rule.maximum_count or 0
		if actual < minimum or (maximum and actual > maximum):
			text = rule_text(rule)
			message = _("Rule: {0}. {1} in office on {2}.").format(text, actual, formatdate(on_date))
			shortfalls.append(
				frappe._dict(
					category=rule.category,
					minimum=minimum,
					maximum=maximum,
					actual=actual,
					rule=text,
					message=message,
				)
			)
	return shortfalls


def rule_text(rule):
	minimum, maximum = rule.minimum_count or 0, rule.maximum_count or 0
	category = _(rule.category)
	if maximum and maximum == minimum:
		return _("exactly {0} {1}").format(minimum, category)
	if maximum:
		return _("{0} to {1} {2}").format(minimum, maximum, category)
	return _("at least {0} {1}").format(minimum, category)


def mandatory_quorum_categories(rules):
	return [rule.category for rule in rules if rule.mandatory_for_quorum]


def shortfall_gap(shortfall):
	"""How far the count is from the rule (members missing, or members over the maximum)."""
	return (
		shortfall.minimum - shortfall.actual
		if shortfall.actual < shortfall.minimum
		else shortfall.actual - shortfall.maximum
	)


def is_worse(new_shortfalls, old_shortfalls):
	"""True when a rule is broken now that was not before, or is broken by more members than before."""
	before = {s.category: shortfall_gap(s) for s in old_shortfalls}
	return any(shortfall_gap(s) > before.get(s.category, 0) for s in new_shortfalls)
