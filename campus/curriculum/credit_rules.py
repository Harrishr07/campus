"""M03-01 Curriculum credit logic: derivation from L-T-P, category totals, range and minimum checks.

Pure functions; the rates and bounds come from the regulation's Curriculum Rule record.
"""

from frappe import _
from frappe.utils import flt


def derive_credits(lecture, tutorial, practical, rule):
	"""Credits of an L-T-P pattern at the rates of `rule` (e.g. R2022: 1 / 1 / 0.5, so 3-0-2 = 4)."""
	return flt(
		flt(lecture) * flt(rule.lecture_credit_per_period)
		+ flt(tutorial) * flt(rule.tutorial_credit_per_period)
		+ flt(practical) * flt(rule.practical_credit_per_period),
		2,
	)


def category_totals(rows, counts):
	"""(credits per category, total of categories that count toward the programme credits).

	`rows` are (category, credits) pairs; `counts` maps category -> counts_toward_credits.
	"""
	totals = {}
	for category, credits in rows:
		totals[category] = flt(totals.get(category, 0) + flt(credits), 2)
	counted = flt(sum(credits for category, credits in totals.items() if counts.get(category)), 2)
	return totals, counted


def range_problem(total, minimum, maximum):
	"""Message when `total` is outside the regulation's range (a bound of 0 means no bound), else None."""
	if minimum and total < minimum:
		return _("Total credits {0} are below the regulation minimum {1}.").format(total, minimum)
	if maximum and total > maximum:
		return _("Total credits {0} are above the regulation maximum {1}.").format(total, maximum)


def credit_shortfalls(totals, minimums):
	"""(category, actual, required) for every category whose total is below its minimum."""
	return [
		(category, flt(totals.get(category, 0)), required)
		for category, required in minimums.items()
		if flt(totals.get(category, 0)) < required
	]
