"""M03-04 Registration rules: pure checks of a Course Registration against a Registration Rule.

No database access. Rows are (registration_type, credits) pairs; every limit comes from the regulation's
Registration Rule record (e.g. R2022: 36 credits excluding arrear/withdrawal, drop 6 credits within
30 days, add 6 credits / 2 courses from semester V, elective minimum enrolment 10). Each check returns
a list of problem messages that cite the regulation clause.
"""

from frappe import _
from frappe.utils import add_days, cint, flt, getdate

def n(value):
	"""A credit figure without a trailing .0."""
	return f"{flt(value):g}"


TYPES = ("Regular", "Arrear", "Dropped", "Additional", "Honours", "Minor")


def clause(regulation_code, clause_no):
	"""Message prefix such as 'R2022 cl. 6.1: '."""
	return f"{regulation_code} cl. {clause_no}: " if clause_no else f"{regulation_code}: "


def excluded_types(text):
	return {line.strip() for line in (text or "").replace(",", "\n").splitlines() if line.strip()}


def counted_credits(rows, excluded):
	"""Credits that count toward the semester limit: rows whose type is not excluded."""
	return flt(sum(flt(credits) for kind, credits in rows if kind not in excluded), 2)


def credit_limit_problems(rows, limit, excluded, prefix):
	total = counted_credits(rows, excluded)
	if limit and total > limit:
		return [
			prefix
			+ _("{0} credits registered; the maximum is {1} per semester (excluding {2}).").format(
				n(total), n(limit), ", ".join(sorted(excluded)) or _("nothing")
			)
		]
	return []


def drop_deadline(term_start, window_days, override=None):
	"""Last day a course may be dropped: the window's own date, else term start plus the drop days."""
	return getdate(override) if override else add_days(getdate(term_start), cint(window_days))


def drop_problems(rows, on_date, deadline, max_credits, prefix):
	dropped = flt(sum(flt(credits) for kind, credits in rows if kind == "Dropped"), 2)
	if not dropped:
		return []
	problems = []
	if getdate(on_date) > getdate(deadline):
		problems.append(prefix + _("courses can be dropped only until {0}.").format(getdate(deadline)))
	if dropped > flt(max_credits):
		problems.append(prefix + _("{0} credits dropped; at most {1} may be dropped.").format(n(dropped), n(max_credits)))
	return problems


def add_problems(rows, semester, rule, prefix):
	added = [flt(credits) for kind, credits in rows if kind == "Additional"]
	if not added:
		return []
	if cint(semester) < cint(rule.add_from_semester):
		return [prefix + _("additional courses are allowed from semester {0}.").format(rule.add_from_semester)]
	problems = []
	if sum(added) > flt(rule.max_add_credits):
		problems.append(
			prefix + _("{0} additional credits; at most {1} may be added.").format(n(sum(added)), n(rule.max_add_credits))
		)
	if len(added) > cint(rule.max_add_courses):
		problems.append(
			prefix + _("{0} additional courses; at most {1} may be added.").format(len(added), cint(rule.max_add_courses))
		)
	return problems


def seat_problem(course, enrolled, seat_cap, prefix):
	"""Message when a new registration would exceed the seat cap (0 = no cap)."""
	if cint(seat_cap) and cint(enrolled) >= cint(seat_cap):
		return prefix + _("elective {0} is full: all {1} seats are taken.").format(course, cint(seat_cap))


def elective_status(enrolled, minimum, window_closed):
	"""'Below Minimum' once the window has closed under the minimum, 'Filling' while open, else 'OK'."""
	if cint(enrolled) >= cint(minimum):
		return "OK"
	return "Below Minimum" if window_closed else "Filling"


def term_parity(term_name, term_start):
	"""1 if the term runs odd semesters, 0 for even: from the name ('Odd'/'Even'), else the start month."""
	name = (term_name or "").lower()
	if "odd" in name:
		return 1
	if "even" in name:
		return 0
	return 1 if getdate(term_start).month >= 6 else 0
