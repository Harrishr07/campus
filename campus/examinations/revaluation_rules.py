"""M06-06 Revaluation rules, pure (no database): the application window counted from publication, the fee and the
direction of a mark change. The window length and the fee rates are records (Exam Rule Set, Exam Fee Rate)."""

from frappe.utils import date_diff, flt

INCREASED, DECREASED, UNCHANGED = "Increased", "Decreased", "Unchanged"


def window_open(published_on, on, days):
	"""True when `on` falls on the publication day or within `days` days after it; never without a window."""
	if not published_on or not days:
		return False
	return 0 <= date_diff(on, published_on) <= int(days)


def fee_total(rate_per_course, courses):
	return flt(rate_per_course) * courses


def change_direction(old, new):
	diff = round(flt(new) - flt(old), 2)
	return INCREASED if diff > 0 else DECREASED if diff < 0 else UNCHANGED


def grievance_pct(grievances, appeared):
	return round(grievances * 100 / appeared, 2) if appeared else 0
