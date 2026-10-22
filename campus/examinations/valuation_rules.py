"""M06-04 Valuation rules, pure (no frappe): third-valuation trigger, final ESE mark, bundle completeness and
dummy-number draws. The threshold and the final-mark method are Exam Rule Set records."""

import secrets
from itertools import combinations

from campus.examinations.rules import round_half_up

AVERAGE_OF_CLOSEST_TWO = "Average of Closest Two"
AVERAGE_OF_THIRD_AND_NEARER = "Average of Third and Nearer"
FINAL_METHODS = (AVERAGE_OF_CLOSEST_TWO, AVERAGE_OF_THIRD_AND_NEARER)
DUMMY_DIGITS = 8


def needs_third_valuation(first, second, ese_max, threshold_pct):
	"""True when the two valuations differ by more than `threshold_pct` % of the ESE maximum."""
	return abs(first - second) * 100 > threshold_pct * ese_max


def final_mark(marks, method):
	"""Final ESE mark from {round: mark}, rounded half up to a whole mark.

	Two valuations: their average. Three: the closest pair (Average of Closest Two) or the third with the nearer
	of the first two (Average of Third and Nearer). A tie goes to the higher pair, in the student's favour.
	"""
	if method not in FINAL_METHODS:
		raise ValueError(f"Unknown final valuation method: {method}")
	if len(marks) < 2:
		raise ValueError("A final mark needs at least two valuations.")
	if len(marks) == 2:
		pair = tuple(marks.values())
	elif method == AVERAGE_OF_CLOSEST_TWO:
		pair = min(combinations(marks.values(), 2), key=lambda p: (abs(p[0] - p[1]), -sum(p)))
	else:
		third = marks[3]
		pair = (third, min((marks[1], marks[2]), key=lambda m: (abs(m - third), -m)))
	return round_half_up(sum(pair) / 2)


def missing_scripts(expected_count, received_flags):
	"""Scripts short of the expected count: listed but not received, or never listed."""
	return max(expected_count - sum(1 for flag in received_flags if flag), 0)


def dummy_numbers(count, taken):
	"""`count` new random dummy numbers (strings of DUMMY_DIGITS digits, no leading 0) not in `taken`."""
	low = 10 ** (DUMMY_DIGITS - 1)
	return [str(draw_unique(lambda: low + secrets.randbelow(9 * low), taken)) for _ in range(count)]


def draw_unique(draw, taken):
	"""Draw until the value is not in `taken`; adds it to `taken`."""
	value = draw()
	while value in taken or str(value) in taken:
		value = draw()
	taken.add(value)
	return value
