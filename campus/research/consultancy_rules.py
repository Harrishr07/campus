"""M08-10 Consultancy revenue-share rules: the institution / faculty / staff split of a project's rule and how a pool is
divided among the team. Pure functions; the Consultancy Project and Consultancy Revenue Share controllers apply them.

The rule's three percentages total 100. A pool above 0% needs team members of its category and a 0% pool has none;
within a category the members' shares total 100 (blank shares are made equal). The faculty and staff amounts are
rounded to the paisa and the institution takes the rounding remainder; within a pool the last member takes it."""

import frappe
from frappe import _
from frappe.utils import flt

from campus.research.ipr import default_shares, split_among

CATEGORIES = ("Faculty", "Staff")


def check_rule(institution_percent, faculty_percent, staff_percent):
	percents = (flt(institution_percent), flt(faculty_percent), flt(staff_percent))
	if any(not 0 <= p <= 100 for p in percents):
		frappe.throw(_("Each revenue share must be between 0 and 100%."))
	if flt(sum(percents), 2) != 100:
		frappe.throw(
			_("The institution, faculty and staff shares must total 100% (now {0}%).").format(
				flt(sum(percents), 2)
			)
		)


def check_team(members, pool_percents):
	"""Throw unless every pool above 0% has members of its category, a 0% pool has none, no Employee is listed twice and
	each category's shares total 100. `members` have category, employee and share_percent; `pool_percents` maps
	category to its %.
	Blank shares of a category are set equal first."""
	employees = [m.get("employee") for m in members]
	duplicates = sorted({e for e in employees if employees.count(e) > 1})
	if duplicates:
		frappe.throw(_("Employee {0} is listed more than once in the team.").format(", ".join(duplicates)))
	for category in CATEGORIES:
		rows = [m for m in members if m.get("category") == category]
		if flt(pool_percents.get(category)) and not rows:
			frappe.throw(
				_("Add the {0} members who share the {1}% {0} share.").format(
					_(category).lower(), flt(pool_percents.get(category))
				)
			)
		if rows and not flt(pool_percents.get(category)):
			frappe.throw(
				_("The {0} share is 0%: remove the {0} members from the team.").format(_(category).lower())
			)
		if rows and all(not flt(m.get("share_percent")) for m in rows):
			for row, share in zip(rows, default_shares(len(rows)), strict=True):
				row.share_percent = share
		total = flt(sum(flt(m.get("share_percent")) for m in rows), 2)
		if rows and total != 100:
			frappe.throw(
				_("The {0} members' shares must total 100% (now {1}%).").format(_(category).lower(), total)
			)


def split_pools(amount, institution_percent, faculty_percent, staff_percent):
	"""(institution, faculty, staff) amounts of `amount`; the institution takes the rounding remainder."""
	faculty = flt(flt(amount) * flt(faculty_percent) / 100, 2)
	staff = flt(flt(amount) * flt(staff_percent) / 100, 2)
	return flt(flt(amount) - faculty - staff, 2), faculty, staff


def member_amounts(members, pool_amounts):
	"""[amount] per member, in order: each category's pool amount ({category: amount}) divided by the members' shares."""
	amounts = [0.0] * len(members)
	for category in CATEGORIES:
		indexes = [i for i, m in enumerate(members) if m.get("category") == category]
		shares = split_among(
			flt(pool_amounts.get(category)), [members[i].get("share_percent") for i in indexes]
		)
		for i, share in zip(indexes, shares, strict=True):
			amounts[i] = share
	return amounts
