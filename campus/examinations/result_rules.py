"""M06-05 Pure rules of the Result Run (P2-T19): combining CIA and ESE with an approved moderation and grace
marks, the CIA of an arrear attempt, grace allocation under the Exam Rule Set limits, the overall result and
the change log between two result versions.

No database access: the Result Run (campus.examinations.results) passes plain numbers and dicts. Grace and
moderation are ESE marks: grace is the fewest whole marks that make a failed course pass, given only when the
student's Exam Rule Set allows it and within its per-course, per-student course-count and total limits (0 means
no cap on a count or total).

M06-12 pre-validation: the configuration gaps that stop a Result Run before it starts.
"""

import math

from frappe import _

from campus.examinations.rules import EPSILON, PASS, attempt_cia

REAPPEAR = "Reappear"
INTERNAL_ONLY = "Internal Only"  # the explicit exam type of a course with no end-semester exam (never blank)


def combined_ese(ese, moderation, grace, ese_max):
	"""The ESE after an approved moderation and grace marks, kept within 0 and the ESE maximum."""
	return min(max(ese + moderation + grace, 0), ese_max)


def arrear_cia(earlier_cias, current_cia, carry_forward):
	"""The CIA of this attempt: `earlier_cias` are the CIA of the earlier attempts (oldest first), `current_cia`
	the CIA on this session's mark sheet (None when there is none). Carried forward, the first attempt's counts."""
	attempts = [*earlier_cias, *([current_cia] if current_cia is not None else [])]
	return attempt_cia(attempts, carry_forward) if attempts else 0


def grace_needed(cia, ese, cia_max, ese_max, ese_min_pct, total_min_pct, ese_alone_min_pct=None):
	"""Fewest whole ESE marks that make the course pass: 0 when it passes already, None when even the full ESE
	cannot. `ese_alone_min_pct` is given from the attempt on which the ESE alone may pass (rules.ese_alone_applies):
	the smaller need of the two bases counts."""
	on_total = max(ese_min_pct * ese_max / 100 - ese, total_min_pct * (cia_max + ese_max) / 100 - cia - ese)
	shortfalls = [on_total] if ese_alone_min_pct is None else [on_total, ese_alone_min_pct * ese_max / 100 - ese]
	feasible = [m for m in (max(0, math.ceil(n - EPSILON)) for n in shortfalls) if ese + m <= ese_max + EPSILON]
	return min(feasible) if feasible else None


def allocate_grace(needs, rule):
	"""{course: grace marks} under `rule` (grace_allowed, grace_max_per_course, grace_max_courses, grace_max_total).

	`needs` maps each failed course to grace_needed(). Smallest needs go first (ties by course), so the most
	courses pass; a course needing more than the per-course limit, or more than the budget left, gets none."""
	if not rule.get("grace_allowed"):
		return {}
	per_course, max_courses, budget = rule["grace_max_per_course"], rule["grace_max_courses"], rule["grace_max_total"]
	given = {}
	for course, marks in sorted(needs.items(), key=lambda item: (item[1], item[0])):
		if not marks or marks > per_course + EPSILON:
			continue
		if max_courses and len(given) >= max_courses:
			break
		if budget and sum(given.values()) + marks > budget + EPSILON:
			continue
		given[course] = marks
	return given


def overall_result(results):
	"""Pass when every course row passed, Reappear when any did not, "" when nothing was graded."""
	if not results:
		return ""
	return PASS if all(r == PASS for r in results) else REAPPEAR


def change_log(old, new):
	"""Lines describing what changed between two result versions ({sgpa, cgpa, arrear_count, classification,
	courses: [{course, grade, result, total}]}); "" when nothing did."""
	before = {c["course"]: c for c in old["courses"]}
	after = {c["course"]: c for c in new["courses"]}
	lines = []
	for course in sorted(before.keys() | after.keys()):
		was, now = before.get(course), after.get(course)
		if not was:
			lines.append(f"{course}: added, {outcome(now)}")
		elif not now:
			lines.append(f"{course}: removed, was {outcome(was)}")
		elif (was["grade"], was["result"], was["total"]) != (now["grade"], now["result"], now["total"]):
			lines.append(f"{course}: {outcome(was)} -> {outcome(now)}, total {number(was['total'])} -> {number(now['total'])}")
	for label, field in (("SGPA", "sgpa"), ("CGPA", "cgpa")):
		if old[field] != new[field]:
			lines.append(f"{label}: {number(old[field])} -> {number(new[field])}")
	if (old.get("arrear_count") or 0) != (new.get("arrear_count") or 0):
		lines.append(f"Arrears: {old.get('arrear_count') or 0} -> {new.get('arrear_count') or 0}")
	if (old.get("classification") or "") != (new.get("classification") or ""):
		lines.append(f"Classification: {old.get('classification') or '-'} -> {new.get('classification') or '-'}")
	return "\n".join(lines)


def outcome(row):
	return f"{row['grade']} ({row['result']})"


def number(value):
	return f"{value:g}"


def configuration_gaps(courses, rule_types):
	"""[(label, reason)] of the offered `courses` a Result Run cannot grade. Each course is a dict: label, has_row
	(a curriculum course row exists), exam_type (blank is a gap, never a guess; Internal Only needs no rule),
	course_type and regulations (of its students, None when a student has none). `rule_types` maps a regulation
	with an Exam Rule Set to the course types it covers."""
	gaps = []
	for course in courses:
		if not course["has_row"]:
			gaps.append((course["label"], _("no curriculum course row")))
		elif not course["exam_type"]:
			gaps.append((course["label"], _("no course type")))
		elif course["exam_type"] != INTERNAL_ONLY:
			gaps.extend((course["label"], reason) for reason in rule_gaps(course["course_type"], course["regulations"], rule_types))
	return gaps


def rule_gaps(course_type, regulations, rule_types):
	reasons = []
	for regulation in sorted(regulations, key=lambda r: r or ""):
		if not regulation:
			reasons.append(_("a student has no regulation"))
		elif regulation not in rule_types:
			reasons.append(_("regulation {0} has no Exam Rule Set").format(regulation))
		elif course_type not in rule_types[regulation]:
			reasons.append(_("the Exam Rule Set of {0} has no {1} course type").format(regulation, _(course_type)))
	return reasons
