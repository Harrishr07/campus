"""M06-08 Pure CIA conversion maths (no database access).

A CIA Component Template lists components, each entered out of `max_marks` and worth `weight` converted
marks. A student's converted CIA = sum of (component marks / max_marks x weight), rounded half up to a
whole mark when the template says so, plus the attendance marks (R2026 bands) when the template adds them.
Absent components score 0.
"""

import math

from campus.examinations.rules import round_half_up

# float noise (e.g. 162.5 / 200 x 40 = 32.49999...) must not flip a half-up rounding
NOISE_PLACES = 6


def component_totals(question_marks):
	"""{(student, component): marks} from (student, component, marks, absent) question rows."""
	totals = {}
	for student, component, marks, absent in question_marks:
		key = (student, component)
		totals[key] = totals.get(key, 0.0) + (0.0 if absent else (marks or 0.0))
	return totals


def converted_assessment(components, marks_by_component, round_to_integer=True):
	"""Weighted CIA of one student before attendance marks.

	`components`: [(component, max_marks, weight)]; `marks_by_component`: {component: marks}.
	"""
	weighted = math.fsum(
		marks_by_component.get(component, 0.0) / max_marks * weight
		for component, max_marks, weight in components
	)
	weighted = round(weighted, NOISE_PLACES)
	return round_half_up(weighted, 0 if round_to_integer else 2)


def converted_cia(components, marks_by_component, attendance_marks=0.0, round_to_integer=True):
	"""Converted CIA mark of one student: the weighted assessments plus the attendance marks."""
	return converted_assessment(components, marks_by_component, round_to_integer) + (attendance_marks or 0.0)
