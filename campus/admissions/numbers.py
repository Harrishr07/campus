"""M04-01 Register and roll numbers from the Admission Settings patterns.

A pattern is text and placeholders ({abbr}, {yy}, {yyyy}, {program_code}) ending in a counter token such as
{####}. The text before the counter is the series key; the counter is a Frappe naming series row (`tabSeries`),
read FOR UPDATE and incremented by `getseries` inside the caller's transaction.

Gap behaviour (verified in frappe/model/naming.py): `getseries` writes through the caller's connection, so
the increment is part of the caller's transaction. A rollback, including a rollback to the savepoint Admit
sets, undoes it, and a concurrent admission waiting on the series row then receives the same number: numbers
are unique and gap-free per committed admission. Gaps appear only if something outside that transaction (a
direct commit mid-admission, or a deleted student) consumes a number. The first number of a new series would
race on the INSERT of the series row (the loser fails with a duplicate key), so `ensure_series` creates the
row first with ON DUPLICATE KEY UPDATE (an exclusive lock at once: INSERT IGNORE takes a shared lock first and
deadlocks when several admissions start the series together), which waits for the other transaction instead of failing.
"""

import re

import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import getdate

PLACEHOLDERS = {"abbr", "yy", "yyyy", "program_code"}
COUNTER = re.compile(r"^(.*)\{(#{2,})\}$")


def validate_pattern(pattern):
	match = COUNTER.match(pattern or "")
	if not match:
		frappe.throw(_("The pattern {0} must end with a counter such as {1}.").format(pattern, "{####}"))
	unknown = set(re.findall(r"{(\w*)}", match.group(1))) - PLACEHOLDERS
	if unknown:
		frappe.throw(_("Unknown placeholder {0} in {1}.").format(", ".join(sorted(unknown)), pattern))


def render_prefix(pattern, company, program, academic_year):
	"""The text of `pattern` before its counter, placeholders filled in."""
	validate_pattern(pattern)
	head = COUNTER.match(pattern).group(1)
	year = getdate(frappe.db.get_value("Academic Year", academic_year, "year_start_date")).year
	values = {"abbr": frappe.get_cached_value("Company", company, "abbr"), "yy": str(year)[-2:], "yyyy": year}
	if "{program_code}" in head:
		code = frappe.get_cached_value("Program", program, "program_abbreviation")
		if not code:
			frappe.throw(
				_("Program {0} has no abbreviation for the {1} placeholder.").format(
					program, "{program_code}"
				)
			)
		values["program_code"] = code
	return head.format(**values)


def next_number(pattern, company, program, academic_year):
	"""The next number of the series `pattern` renders to. Holds the series row lock until the caller commits."""
	prefix = render_prefix(pattern, company, program, academic_year)
	ensure_series(prefix)
	return prefix + getseries(prefix, len(COUNTER.match(pattern).group(2)))


def ensure_series(prefix):
	frappe.db.sql(
		"INSERT INTO `tabSeries` (`name`, `current`) VALUES (%s, 0) ON DUPLICATE KEY UPDATE `name` = `name`",
		(prefix,),
	)
