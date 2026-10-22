"""M17-06 COE report rules, pure (no database): appeared / passed tallies, pass percentage, competition ranks and
the days from the exam end to the declaration of results (AQAR 2.5.1, 2.6.3).

A unit (a Student Result, or one course of it) appeared when at least one of its outcomes is a sitting (Pass or
Fail; SA, AB, WD and Pending are not) and passed when, in addition, every outcome is a Pass."""

from frappe.utils import date_diff, getdate

SAT = ("Pass", "Fail")
PASS = "Pass"


def tally(rows, group_of, unit_of):
	"""{group: {appeared, passed}} over the units of `rows` (each row has an `outcome`); a unit takes the group of its first row."""
	units = {}
	for row in rows:
		unit = units.setdefault(unit_of(row), {"group": group_of(row), "outcomes": set()})
		unit["outcomes"].add(row["outcome"])
	out = {}
	for unit in units.values():
		if not set(SAT) & unit["outcomes"]:
			continue
		counts = out.setdefault(unit["group"], {"appeared": 0, "passed": 0})
		counts["appeared"] += 1
		counts["passed"] += unit["outcomes"] == {PASS}
	return out


def percent(part, whole):
	return round(part * 100 / whole, 2) if whole else 0


def competition_ranks(scores):
	"""Ranks of `scores` (already highest first): equal scores share a rank and the next rank skips (1, 2, 2, 4)."""
	ranks = []
	for index, score in enumerate(scores):
		ranks.append(ranks[-1] if index and score == scores[index - 1] else index + 1)
	return ranks


def days_to_result(exam_end, published_at):
	"""Days from the last exam to the day the results were declared, or None without both dates."""
	if not exam_end or not published_at:
		return None
	return date_diff(getdate(published_at), getdate(exam_end))


def average(values):
	return round(sum(values) / len(values), 2) if values else 0
