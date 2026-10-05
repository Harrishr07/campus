"""M12-02 Pure examination rule maths: pass decision, grade lookup, SGPA and CGPA.

No database access: callers pass the rule values (Exam Rule Set row, Grading Scheme rows) as plain numbers
and dicts, so every branch is unit-testable. Marks are compared as percentages of their maxima, so a
course scored out of 40 + 60 and one scored out of 50 + 50 use the same rule.
"""

from decimal import ROUND_HALF_UP, Decimal

FAIL_LETTER = "U"
EPSILON = 1e-9


def pct(mark, maximum):
	return mark * 100 / maximum if maximum else 0.0


def total_pct(cia, ese, cia_max, ese_max):
	"""CIA + ESE scaled to 100."""
	return pct(cia + ese, cia_max + ese_max)


def pass_status(cia, ese, cia_max, ese_max, ese_min_pct, total_min_pct):
	"""True when the ESE reaches `ese_min_pct` of its maximum and the total reaches `total_min_pct`."""
	return (
		pct(ese, ese_max) >= ese_min_pct - EPSILON
		and total_pct(cia, ese, cia_max, ese_max) >= total_min_pct - EPSILON
	)


def round_half_up(value, places=0):
	quantum = Decimal(1).scaleb(-places)
	return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def grade(total, grades):
	"""(letter, grade_point) of the scheme row whose [min_mark, max_mark] holds `total`.

	`total` (0-100) is rounded half up to a whole mark first, as the published mark ranges are whole
	numbers. `grades` is a list of dicts with letter, grade_point, min_mark, max_mark.
	"""
	mark = round_half_up(total)
	for row in grades:
		if row["min_mark"] <= mark <= row["max_mark"]:
			return row["letter"], row["grade_point"]
	raise ValueError(f"No grade covers {mark}")


def gpa(courses):
	"""Σ(credits × grade point) / Σ credits over passed courses, 2 decimals; 0 when none passed.

	`courses` is a list of (credits, grade_point, passed).
	"""
	passed = [(credits, point) for credits, point, ok in courses if ok]
	credits = sum(c for c, _p in passed)
	if not credits:
		return 0.0
	return round_half_up(sum(c * p for c, p in passed) / credits, 2)


sgpa = gpa


def cgpa(attempts):
	"""GPA over every attempt, a later pass of a course replacing an earlier one.

	`attempts` is chronological (course, credits, grade_point, passed).
	"""
	latest = {}
	for course, credits, point, ok in attempts:
		if ok:
			latest[course] = (credits, point, True)
	return gpa(list(latest.values()))
