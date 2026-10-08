"""M06-01, M05-03 Exam withdrawal and break of study rules (pure, no frappe).

Withdrawal (R2022 cl. on withdrawal from examination): once in the programme, applied within the regulation's
window of days after the exam of the course. Only the Principal's special case lifts the window; nothing lifts
once-per-programme. The result code is the regulation's own withdrawal code (WD in R2022, WC in R2026), read
from its Grading Scheme codes.

Break of study: the regulation's maximum years, plus its exceptional years when the break is marked
exceptional, over all of the student's breaks together.
"""

REPEAT, LATE = "repeat", "late"
EXCEEDS, BAD_DATES = "exceeds", "bad dates"
WITHDRAWN = "WD"  # the Student Result Course result of a withdrawn course (its grade is the regulation's code)
YEAR_DAYS = 366  # the longest calendar year: a break of exactly one calendar year always fits


def days_after_exam(exam_date, applied_on):
	"""Days from the exam to the application; negative when applied before the exam."""
	return (applied_on - exam_date).days


def withdrawal_refusal(earlier_withdrawals, days_after, window_days, special_case):
	"""None when the withdrawal is allowed, else REPEAT (one already in the programme) or LATE (past the window)."""
	if earlier_withdrawals:
		return REPEAT
	if days_after > window_days and not special_case:
		return LATE
	return None


def withdrawal_code(scheme_codes, withdrawal_codes):
	"""The first of the scheme's result codes that is a withdrawal code, or None."""
	return next((code for code in scheme_codes if code in withdrawal_codes), None)


def break_days(from_date, to_date):
	"""Days of a break, both dates inclusive."""
	return (to_date - from_date).days + 1


def break_refusal(used_days, requested_days, max_years, exceptional_years, exceptional):
	"""None when the break fits, else BAD_DATES (it ends before it starts) or EXCEEDS (past the limit).

	`used_days` are the student's other approved breaks; the exceptional years count only for an exceptional break.
	"""
	if requested_days < 1:
		return BAD_DATES
	years = max_years + (exceptional_years if exceptional else 0)
	if used_days + requested_days > years * YEAR_DAYS:
		return EXCEEDS
	return None
