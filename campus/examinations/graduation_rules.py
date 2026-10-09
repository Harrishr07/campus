"""M06-07, M05-03 Graduate record rules (pure, no database): consolidate a student's published course attempts into
the consolidated grade sheet values (CGPA, % = CGPA x 10, outstanding arrears, additional / Honours / Minor courses),
classify it by the regulation's Classification Rule, decide a term-end progression, and neutralise export cells.

Additional, Honours and Minor courses (their Course Registration type) are listed apart from the core courses and
enter the CGPA only when the Grading Scheme counts them (count_additional_with_honours) and the student completed the
Honours or Minor: passed courses of that type worth the Classification Rule's honours_credits. They are never
arrears. A course's latest pass is listed (the one rules.cgpa counts), else its latest attempt. Withdrawn (WD), SA
and Pending courses stay arrears until passed, as in campus.examinations.arrears (T21: a withdrawal is no attempt
or appearance, but the course is still owed). The core credits passed are checked against the regulation's credit
total by credits_complete.
"""

from campus.examinations import rules

PASS = rules.PASS
REGULAR, HONOURS, MINOR = "Regular", "Honours", "Minor"
ADDITIONAL_TYPES = ("Additional", HONOURS, MINOR)
PROMOTE, DETAIN, PROBATION = "Promote", "Detain", "Probation"
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def specialisation(attempts, registration_types, credits_needed):
	"""Honours or Minor when the passed credits of courses registered as such reach `credits_needed` (0: none
	offered), else Regular."""
	if not credits_needed:
		return REGULAR
	for variant in (HONOURS, MINOR):
		passed = {a["course"]: a["credits"] for a in attempts if a["result"] == PASS and registration_types.get(a["course"]) == variant}
		if sum(passed.values()) >= credits_needed:
			return variant
	return REGULAR


def consolidate(attempts, registration_types, credits_needed=0, count_additional=False):
	"""The consolidated values of chronological `attempts` (dicts with course, credits, grade, grade_point, result,
	in_gpa). `registration_types` maps a course to Additional / Honours / Minor (others are core)."""
	variant = specialisation(attempts, registration_types, credits_needed)
	additional_counts = bool(count_additional) and variant != REGULAR
	final = {}
	for row in attempts:
		if row["result"] == PASS or final.get(row["course"], {}).get("result") != PASS:
			final[row["course"]] = row
	counted = {}
	courses = []
	for course, row in final.items():
		kind = registration_types.get(course) or REGULAR
		counted[course] = bool(row["in_gpa"]) and rules.counts_in_gpa({"additional": kind in ADDITIONAL_TYPES}, (), additional_counts)
		courses.append({**row, "registration_type": kind, "in_cgpa": counted[course]})
	core = [c for c in courses if c["registration_type"] not in ADDITIONAL_TYPES]
	core_names = {c["course"] for c in core}
	history = {}
	for row in attempts:
		if row["course"] in core_names:
			history.setdefault(row["course"], []).append(row["result"])
	cgpa = rules.cgpa([(a["course"], a["credits"], a["grade_point"], a["result"] == PASS) for a in attempts if counted[a["course"]]])
	return {
		"variant": variant,
		"cgpa": cgpa,
		"percentage": rules.percentage(cgpa),
		"core_courses": core,
		"additional_courses": [c for c in courses if c["registration_type"] in ADDITIONAL_TYPES],
		"arrears": sorted(c["course"] for c in core if c["result"] != PASS),
		"first_appearance": rules.passed_at_first_appearance(history),
		"core_credits": sum(c["credits"] for c in core if c["result"] == PASS),
	}


def credits_complete(record, required_credits):
	"""Whether the passed core credits reach the regulation's total (0 or None: no total on record, not checked)."""
	return not required_credits or record["core_credits"] >= required_credits


def classification(record, classes, years_taken, break_years, entry_type):
	"""(class name, variant) of a consolidated `record` by Classification Rule rows `classes`, or None while an
	arrear is outstanding."""
	if record["arrears"] or not record["core_courses"]:
		return None
	return rules.classify(
		record["cgpa"], classes, variant=record["variant"], first_appearance=record["first_appearance"],
		years_taken=years_taken, break_years=break_years, entry_type=entry_type,
	)  # fmt: skip


def progression_outcome(arrear_count, cgpa, max_arrears, probation_below_cgpa):
	"""Detain above `max_arrears` outstanding arrears; else Probation below `probation_below_cgpa` (0: never; a
	student without a CGPA yet is not on probation); else Promote."""
	if arrear_count > max_arrears:
		return DETAIN
	if probation_below_cgpa and cgpa and cgpa < probation_below_cgpa:
		return PROBATION
	return PROMOTE


def csv_cell(value):
	"""An export cell that a spreadsheet will not run as a formula; None is blank."""
	if value is None:
		return ""
	if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
		return "'" + value
	return value
