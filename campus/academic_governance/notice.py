"""M02-03 Notice timing: a notice must go out at least `notice_days` before the meeting."""

from frappe.utils import date_diff


def notice_is_late(meeting_date, sent_on, notice_days):
	return date_diff(meeting_date, sent_on) < (notice_days or 0)
