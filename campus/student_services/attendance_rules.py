"""M05-02 Attendance eligibility maths. Pure functions: thresholds come from an Attendance Rule record.

Decision, for one student and term (courses with nothing conducted are ignored):
- Eligible: overall % >= overall minimum and, when a per-course minimum is set, every course % >= it.
- Medical band: not Eligible, but the student has approved medical leave and, counting those leave
  periods as attended, overall % >= the medical band minimum and every course % still meets the
  per-course minimum. Leave counts only here, never in the reported percentages.
- Shortage (SA): otherwise.
Overall % is all attended / all conducted (`sum_based`) or the mean of the course % (`course_average`).
With nothing conducted at all there is nothing to fall short of: Eligible, overall None.
"""

ELIGIBLE = "Eligible"
MEDICAL_BAND = "Medical band"
SHORTAGE = "Shortage"


def percentage(attended, conducted):
	return attended * 100.0 / conducted if conducted else 0.0


def overall_percentage(formula, courses):
	"""`courses` is a list of (conducted, attended) pairs; None when no period was conducted."""
	held = [(conducted, attended) for conducted, attended in courses if conducted]
	if not held:
		return None
	if formula == "course_average":
		return sum(percentage(attended, conducted) for conducted, attended in held) / len(held)
	return percentage(sum(a for _c, a in held), sum(c for c, _a in held))


def meets_minimums(rule, courses):
	"""True if the overall % and (when set) each course % reach the rule's minimums."""
	overall = overall_percentage(rule["formula"], courses)
	if overall is None:
		return True
	return overall >= rule["overall_min_pct"] and courses_meet(rule["per_course_min_pct"], courses)


def courses_meet(minimum, courses):
	return all(percentage(attended, conducted) >= minimum for conducted, attended in courses if conducted)


def eligibility(rule, courses):
	"""Status for `courses`, a list of (conducted, attended, approved_leave) per course; `rule` a dict."""
	raw = [(conducted, attended) for conducted, attended, _leave in courses]
	if meets_minimums(rule, raw):
		return ELIGIBLE
	with_leave = [(conducted, attended + leave) for conducted, attended, leave in courses]
	if sum(leave for _c, _a, leave in courses) == 0:
		return SHORTAGE
	band_rule = {**rule, "overall_min_pct": rule["medical_band_min_pct"]}
	return MEDICAL_BAND if meets_minimums(band_rule, with_leave) else SHORTAGE
