"""M12-05 Lab rules that need no database: when a calibration notice is due and how a safety inspection turns out."""

from frappe.utils import date_diff, getdate


def days_left(next_due_date, on_date):
	"""Days from `on_date` to the due date; negative once it has passed."""
	return date_diff(getdate(next_due_date), getdate(on_date))


def notice_due(next_due_date, on_date, notice_days):
	"""True from `notice_days` ahead of the due date up to and including the due date itself."""
	return 0 <= days_left(next_due_date, on_date) <= int(notice_days)


def inspection_outcome(points):
	"""Fail when a critical point is not met, Needs Action when only other points are not, else Pass.

	`points` need `compliant` and `critical` (rows or dicts).
	"""
	missed = [point for point in points if not _get(point, "compliant")]
	if any(_get(point, "critical") for point in missed):
		return "Fail"
	return "Needs Action" if missed else "Pass"


def _get(point, key):
	return point.get(key) if hasattr(point, "get") else getattr(point, key)
