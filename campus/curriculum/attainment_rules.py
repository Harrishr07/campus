"""M03-03 Attainment maths, pure: no reads or writes. Every weight, threshold, band and target comes from the
regulation's Attainment Policy (campus.curriculum.attainment).

- A student's score on a CO in a tool (CIA or ESE) is the sum of their marks on the questions tagged with that CO over
  the sum of those questions' maxima; a question they were absent for counts in neither.
- The tool's attainment is the share of the students assessed on the CO who score at least the student threshold, mapped
  to the highest level band it reaches (0 below the first band).
- Direct = CIA level x CIA weight + ESE level x ESE weight; a tool with no question tagged with the CO drops out and the
  other carries the direct alone. Indirect = the exit-survey mean rating as a share of 5, scaled to the top level.
  Final = direct x direct weight + indirect x indirect weight; without a survey score the final is the direct.
- PO / PSO = sum(CO final x correlation) / sum(correlation) over the COs mapped to it; final with the programme exit
  survey at the policy's PO indirect weight.
Every level is rounded to 2 places and the next step uses the rounded figure, as the NBA course file shows it.
A missing figure is None here; stored, it is 0 with its flag off (assessed / mapped / has_indirect), see `shown`.
"""

from collections import namedtuple

from frappe.utils import flt

Policy = namedtuple(
	"Policy", "direct_weight indirect_weight cia_weight ese_weight student_threshold bands target_level"
)  # bands: ((level, minimum % of students), ...)

NO_CIA = "No CIA question is tagged with this CO."
NO_ESE = "No ESE question is tagged with this CO."
NO_INDIRECT = "No survey score (no closed course exit survey, or too few answers to show)."
NO_DIRECT = "Not assessed: no tagged question was answered."
NOT_MAPPED = "No CO maps to this outcome."
NO_EXIT_SURVEY = "No exit survey score (none chosen, or too few answers to show)."


class Result(dict):
	__getattr__ = dict.get


def student_scores(rows):
	"""{student: (marks, maximum)} over `rows` ({student, marks, max_marks, absent}); absent rows are left out."""
	scores = {}
	for row in rows:
		if row.get("absent"):
			continue
		marks, maximum = scores.get(row["student"], (0, 0))
		scores[row["student"]] = (marks + flt(row["marks"]), maximum + flt(row["max_marks"]))
	return {student: score for student, score in scores.items() if score[1] > 0}


def attains(score, threshold):
	marks, maximum = score
	return marks * 100 >= threshold * maximum


def tool_attainment(scores, threshold):
	"""(students, attained, percent) of `scores` at the student threshold %; percent None when nobody was assessed."""
	attained = sum(1 for score in scores.values() if attains(score, threshold))
	return len(scores), attained, flt(attained * 100 / len(scores), 2) if scores else None


def level_for(percent, bands):
	"""The highest band level whose minimum `percent` reaches; 0 below every band, None without a percent."""
	if percent is None:
		return None
	return max((level for level, minimum in bands if percent >= minimum), default=0)


def top_level(bands):
	return max(level for level, _minimum in bands)


def indirect_level(percent, top):
	return None if percent is None else flt(percent * top / 100, 2)


def weighted(parts):
	"""Weighted mean of (value, weight) parts, leaving out missing values; None when nothing is left to weigh."""
	present = [(value, weight) for value, weight in parts if value is not None]
	total = sum(weight for _value, weight in present)
	if not total:
		return None
	return flt(sum(value * weight for value, weight in present) / total, 2)


def gap(final, target):
	"""How far below the target the final level is (None when met or not assessed)."""
	if final is None or final >= target:
		return None
	return flt(target - final, 2)


def co_result(cia, ese, indirect_percent, policy):
	"""One CO's figures from its (students, attained, percent) per tool and its survey percent (None if none)."""
	cia_level, ese_level = level_for(cia[2], policy.bands), level_for(ese[2], policy.bands)
	direct = weighted([(cia_level, policy.cia_weight), (ese_level, policy.ese_weight)])
	indirect = indirect_level(indirect_percent, top_level(policy.bands))
	final = weighted([(direct, policy.direct_weight), (indirect, policy.indirect_weight)]) if direct is not None else None
	notes = [
		note for note, missing in ((NO_CIA, cia[2] is None), (NO_ESE, ese[2] is None), (NO_INDIRECT, indirect is None), (NO_DIRECT, direct is None))
		if missing
	]  # fmt: skip
	return Result(
		cia_students=cia[0], cia_attained=cia[1], cia_percent=cia[2], cia_level=cia_level,
		ese_students=ese[0], ese_attained=ese[1], ese_percent=ese[2], ese_level=ese_level,
		direct_level=direct, indirect_percent=indirect_percent, indirect_level=indirect, final_level=final,
		target_level=policy.target_level, target_met=int(final is not None and final >= policy.target_level),
		gap=gap(final, policy.target_level), notes=notes, assessed=int(direct is not None), has_indirect=int(indirect is not None),
	)  # fmt: skip


def po_direct(cells):
	"""sum(CO final x correlation) / sum(correlation) over (final, correlation) cells with a final and a correlation."""
	mapped = [(final, correlation) for final, correlation in cells if final is not None and correlation]
	return weighted(mapped) if mapped else None


def po_result(direct, indirect_percent, top, indirect_weight, target_level):
	indirect = indirect_level(indirect_percent, top)
	final = weighted([(direct, 100 - indirect_weight), (indirect, indirect_weight)]) if direct is not None else None
	notes = [note for note, missing in ((NOT_MAPPED, direct is None), (NO_EXIT_SURVEY, indirect is None)) if missing]
	return Result(
		direct_level=direct, indirect_percent=indirect_percent, indirect_level=indirect, final_level=final,
		target_level=target_level, target_met=int(final is not None and final >= target_level),
		gap=gap(final, target_level), notes=notes, mapped=int(direct is not None), has_indirect=int(indirect is not None),
	)  # fmt: skip


FLAGS = {"cia_percent": "cia_students", "cia_level": "cia_students", "ese_percent": "ese_students", "ese_level": "ese_students",
	"direct_level": ("assessed", "mapped"), "final_level": ("assessed", "mapped"), "indirect_level": "has_indirect",
	"indirect_percent": "has_indirect"}  # fmt: skip


def shown(row):
	"""A stored result row with its missing figures as None (a Float column stores None as 0)."""
	row = dict(row)
	for field, flags in FLAGS.items():
		if field in row and not any(row.get(flag) for flag in ((flags,) if isinstance(flags, str) else flags)):
			row[field] = None
	return row
