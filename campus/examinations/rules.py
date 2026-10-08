"""M12-02, M06-05, M05-03 Pure examination rule maths: attempts, pass decision, absolute and relative
(Box-Cox) grades, SGPA, CGPA and classification.

No database access: callers pass the rule values (Exam Rule Set, Grading Scheme, Classification Rule rows)
as plain numbers and dicts, so every branch is unit-testable. Marks are compared as percentages of their
maxima, so a course scored out of 40 + 60 and one scored out of 50 + 50 use the same rule.

Box-Cox is implemented here in pure Python (maximum-likelihood lambda by golden-section search) because
neither scipy nor numpy is installed in the bench environment, and a pure function keeps the bands
reproducible: the input is sorted and summed with math.fsum, and the search runs a fixed number of steps.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

FAIL_LETTER = "U"
EPSILON = 1e-9
PASS, FAIL, ABSENT = "Pass", "Fail", "AB"
WITHDRAWAL_CODES = ("W", "WD", "WC")
ALWAYS_ABSOLUTE = ("Lab", "Project")
ABSOLUTE, RELATIVE, ONLINE = "Absolute", "Relative Box-Cox", "Online Table"
REGULAR = "Regular"
LAMBDA_RANGE = (-5.0, 5.0)
LAMBDA_STEPS = 200


def pct(mark, maximum):
	return mark * 100 / maximum if maximum else 0.0


def total_pct(cia, ese, cia_max, ese_max):
	"""CIA + ESE scaled to 100."""
	return pct(cia + ese, cia_max + ese_max)


def reaches(value, minimum):
	return value >= minimum - EPSILON


def pass_basis(
	cia,
	ese,
	cia_max,
	ese_max,
	ese_min_pct,
	total_min_pct,
	attempt=1,
	ese_only_from_attempt=0,
	ese_only_min_pct=0,
):
	"""How the course is passed: "total" (ESE and total minimums met), "ese" (from attempt
	`ese_only_from_attempt` on, the ESE alone reaches `ese_only_min_pct`), or None for a fail."""
	if reaches(pct(ese, ese_max), ese_min_pct) and reaches(
		total_pct(cia, ese, cia_max, ese_max), total_min_pct
	):
		return "total"
	if (
		ese_only_from_attempt
		and attempt >= ese_only_from_attempt
		and reaches(pct(ese, ese_max), ese_only_min_pct)
	):
		return "ese"
	return None


def pass_status(cia, ese, cia_max, ese_max, ese_min_pct, total_min_pct, **attempt_rule):
	"""True when the course is passed; `attempt_rule` takes pass_basis()'s attempt keywords."""
	return pass_basis(cia, ese, cia_max, ese_max, ese_min_pct, total_min_pct, **attempt_rule) is not None


def graded_mark(cia, ese, cia_max, ese_max, basis):
	"""The 0-100 mark a pass is graded on: the total, or the ESE % when the ESE alone passed the course."""
	return pct(ese, ese_max) if basis == "ese" else total_pct(cia, ese, cia_max, ese_max)


def internal_pass(cia, cia_max, internal_only_min_pct):
	"""Pass of an Internal Only course (no ESE): the CIA reaches its pass % of the CIA maximum."""
	return reaches(pct(cia, cia_max), internal_only_min_pct)


def attempt_number(prior_results, absent_counts_as_attempt):
	"""Number of the next attempt at a course given its earlier results (oldest first).

	A fail counts as an attempt, an absence only when the rule says so; a withdrawal or a shortage of
	attendance (the student did not sit) never does.
	"""
	counted = (FAIL, ABSENT) if absent_counts_as_attempt else (FAIL,)
	return 1 + sum(1 for result in prior_results if result in counted)


def may_attempt(attempt, max_attempts):
	"""False once `attempt` exceeds the regulation's maximum attempts (0: no limit)."""
	return not max_attempts or attempt <= max_attempts


def attempt_cia(cia_by_attempt, carry_forward):
	"""CIA marks used for the latest attempt: the first attempt's when carried forward, else the latest."""
	return cia_by_attempt[0] if carry_forward else cia_by_attempt[-1]


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


def grading_method(course_type, method, passed_count, min_cohort):
	"""The method that grades a course: relative only when more than `min_cohort` students passed it;
	labs and projects are always absolute; a course type without a method row (`method` None) is absolute."""
	if course_type in ALWAYS_ABSOLUTE or not method:
		return ABSOLUTE
	if method == RELATIVE and passed_count <= min_cohort:
		return ABSOLUTE
	return method


def boxcox(value, lam):
	return math.log(value) if abs(lam) < EPSILON else (value**lam - 1) / lam


def inverse_boxcox(value, lam):
	if abs(lam) < EPSILON:
		return math.exp(value)
	base = lam * value + 1
	return base ** (1 / lam) if base > 0 else 0.0


def mean_sd(values):
	mean = math.fsum(values) / len(values)
	return mean, math.sqrt(math.fsum((v - mean) ** 2 for v in values) / len(values))


def boxcox_log_likelihood(values, lam):
	"""Profile log-likelihood of the Box-Cox `lam` for positive `values` (normal errors, MLE variance)."""
	_mean, sd = mean_sd([boxcox(v, lam) for v in values])
	return (lam - 1) * math.fsum(math.log(v) for v in values) - len(values) * math.log(sd)


def boxcox_lambda(values):
	"""Maximum-likelihood Box-Cox lambda in LAMBDA_RANGE (golden-section search), 6 decimals."""
	low, high = LAMBDA_RANGE
	ratio = (math.sqrt(5) - 1) / 2
	for _step in range(LAMBDA_STEPS):
		left, right = high - ratio * (high - low), low + ratio * (high - low)
		if boxcox_log_likelihood(values, left) < boxcox_log_likelihood(values, right):
			low = left
		else:
			high = right
	return round_half_up((low + high) / 2, 6)


def relative_grade_bands(totals, grades):
	"""Relative (Box-Cox normalised) bands for one course: [{letter, grade_point, min_mark}], best first.

	`totals` are the 0-100 marks of the students who passed the course. They are Box-Cox transformed with
	the maximum-likelihood lambda; a pass grade's lower bound is mean + relative_min_z x SD in the transformed
	scale, mapped back to marks (2 decimals) and never below the lowest pass grade's minimum mark, which
	takes every remaining pass. The same totals in any order give the same bands.
	"""
	values = sorted(totals)
	if not values or values[0] <= 0 or values[0] == values[-1]:
		raise ValueError("Relative grading needs positive marks that are not all equal.")
	lam = boxcox_lambda(values)
	mean, sd = mean_sd([boxcox(v, lam) for v in values])
	passes = sorted((g for g in grades if g["is_pass"]), key=lambda g: g["min_mark"], reverse=True)
	floor = passes[-1]["min_mark"]
	bands = [
		{
			"letter": g["letter"],
			"grade_point": g["grade_point"],
			"min_mark": max(floor, round_half_up(inverse_boxcox(mean + g["relative_min_z"] * sd, lam), 2)),
		}
		for g in passes[:-1]
	]
	return [
		*bands,
		{"letter": passes[-1]["letter"], "grade_point": passes[-1]["grade_point"], "min_mark": floor},
	]


def relative_grade(total, bands):
	"""(letter, grade_point) of a passed student's `total` in relative_grade_bands() output."""
	mark = round_half_up(total, 2)
	for band in bands:
		if mark >= band["min_mark"]:
			return band["letter"], band["grade_point"]
	return bands[-1]["letter"], bands[-1]["grade_point"]


def counts_in_gpa(course, excluded_categories, additional_counts=False):
	"""Whether a course enters SGPA/CGPA: not of an excluded category (e.g. mandatory courses), and an
	additional course only when `additional_counts` (the regulation allows it and the Honours or Minor is
	completed). `course` is a dict with category and additional."""
	if course.get("category") in excluded_categories:
		return False
	return additional_counts or not course.get("additional")


def percentage(cgpa_value):
	"""Equivalent percentage of a CGPA: CGPA x 10, 2 decimals."""
	return round_half_up(cgpa_value * 10, 2)


def passed_at_first_appearance(results_by_course):
	"""True when every course was passed at its first appearance; a withdrawal is not an appearance.

	`results_by_course` maps a course to its results (Pass, Fail, SA, AB, WD …), oldest first.
	"""
	for results in results_by_course.values():
		sat = [r for r in results if r not in WITHDRAWAL_CODES]
		if sat[:1] != [PASS]:
			return False
	return True


def classify(cgpa_value, classes, variant=REGULAR, first_appearance=True, years_taken=0, break_years=0):
	"""(class name, variant) of the first Classification Rule row the student meets, or None.

	Rows of the student's `variant` are tried first, then Regular rows (an Honours student below every
	Honours class still gets a regular class). `years_taken` counts from admission to completion including
	any break of study; a row without break_of_study_included discounts `break_years`.
	"""
	ordered = [c for c in classes if c["variant"] == variant]
	if variant != REGULAR:
		ordered += [c for c in classes if c["variant"] == REGULAR]
	for row in ordered:
		years = years_taken if row["break_of_study_included"] else years_taken - break_years
		if (
			reaches(cgpa_value, row["cgpa_min"])
			and (first_appearance or not row["first_appearance_required"])
			and (not row["max_years"] or years <= row["max_years"])
		):
			return row["class_name"], row["variant"]
	return None


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
