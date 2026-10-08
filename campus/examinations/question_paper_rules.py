"""M06-03 Question paper rules (pure): the download window around the release time and the blueprint check.

The window opens `lead_minutes` before release (the slot start) and closes when the slot ends. The pattern needs at
least one CO row and one Bloom row, each with min <= max. The blueprint check then runs per set: the set's marks add up to the paper total, and each pattern row (a course outcome or a
Bloom level with a min-max share of the marks) holds; a question whose CO or Bloom level the pattern does not
list is reported when the pattern lists that criterion at all.
"""

from collections import defaultdict
from datetime import timedelta

from frappe import _
from frappe.utils import flt

CRITERIA = {"Course Outcome": "course_outcome", "Bloom Level": "bloom_level"}


def release_window(release_at, lead_minutes, slot_minutes):
	"""(opens, closes) of the download window."""
	return release_at - timedelta(minutes=lead_minutes), release_at + timedelta(minutes=slot_minutes)


def in_window(now, opens, closes):
	return opens <= now <= closes


def blueprint_issues(questions, blueprint, total_marks, sets_with_files=()):
	"""Issue messages of the paper against its pattern; [] when every set matches. `sets_with_files`: the sets
	that have a paper file attached, each of which needs questions."""
	issues = pattern_issues(blueprint)
	if not questions:
		return [*issues, _("The paper has no questions.")]
	by_set = defaultdict(list)
	for question in questions:
		by_set[question["paper_set"]].append(question)
	issues += [_("Set {0} has a paper file but no questions.").format(s) for s in sets_with_files if s not in by_set]
	for paper_set in sorted(by_set):
		prefix = _("Set {0}").format(paper_set) + ": "
		issues += [prefix + issue for issue in set_issues(by_set[paper_set], blueprint, flt(total_marks))]
	return issues


def pattern_issues(blueprint):
	"""The pattern itself: at least one row per criterion, and min <= max on every row."""
	issues = [_("The pattern needs at least one {0} row.").format(_(criterion)) for criterion in CRITERIA
		if not any(r["criterion"] == criterion for r in blueprint)]  # fmt: skip
	for row in blueprint:
		if flt(row["min_percent"]) > flt(row["max_percent"]):
			issues.append(_("{0}: the minimum share ({1}%) is above the maximum ({2}%).").format(
				row["value"], fmt(row["min_percent"]), fmt(row["max_percent"])))  # fmt: skip
	return issues


def set_issues(questions, blueprint, total_marks):
	marks = sum(flt(q["marks"]) for q in questions)
	if flt(marks, 2) != flt(total_marks, 2):
		return [_("the questions carry {0} marks, the paper {1}.").format(fmt(marks), fmt(total_marks))]
	issues = []
	for criterion, field in CRITERIA.items():
		rows = [r for r in blueprint if r["criterion"] == criterion]
		issues += criterion_issues(questions, rows, field, marks)
	return issues


def criterion_issues(questions, rows, field, marks):
	if not rows:
		return []
	shares = defaultdict(float)
	for question in questions:
		shares[question[field]] += flt(question["marks"]) * 100 / marks
	issues = []
	for row in rows:
		share, low, high = flt(shares.get(row["value"]), 2), flt(row["min_percent"]), flt(row["max_percent"])
		if not share and low:
			issues.append(_("{0} is not covered (the pattern needs at least {1}%).").format(row["value"], fmt(low)))
		elif not low <= share <= high:
			issues.append(_("{0} carries {1}% of the marks, the pattern allows {2}% to {3}%.").format(
				row["value"], fmt(share), fmt(low), fmt(high)))  # fmt: skip
	listed = {row["value"] for row in rows}
	issues += [_("{0} is not in the pattern.").format(value) for value in shares if value not in listed]
	return issues


def fmt(number):
	return f"{flt(number, 2):g}"
