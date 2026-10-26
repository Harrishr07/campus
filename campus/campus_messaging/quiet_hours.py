"""M16-01 Quiet hours: non-urgent messages wait until the quiet window ends."""

from datetime import datetime, timedelta

import frappe
from frappe.utils import get_time


def release_time(now, start, end):
	"""Return the datetime the quiet window containing `now` ends, or None when `now` is outside it.

	`start`/`end` are times (or Time field values); a window with start > end spans midnight.
	"""
	if not start or not end:
		return None
	start, end = get_time(start), get_time(end)
	if start == end:
		return None
	t = now.time()
	in_window = start <= t < end if start < end else (t >= start or t < end)
	if not in_window:
		return None
	release = datetime.combine(now.date(), end)
	if release <= now:
		release += timedelta(days=1)
	return release


def current_release_time(settings, now=None):
	return release_time(
		now or frappe.utils.now_datetime(), settings.quiet_hours_start, settings.quiet_hours_end
	)
