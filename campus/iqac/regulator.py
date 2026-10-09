"""M01-06 Regulator submissions: the due rule, the reminder schedule and the daily run.

The owner is messaged the configured days before the due date; once the due date has passed the owner is told it is overdue and
the Principal of the college is told too, each week until the return is filed. Offsets and due rules are records on the
Regulator Submission Type.
"""

import calendar
import datetime

import frappe
from frappe import _
from frappe.utils import cint, date_diff, getdate, today

from campus.campus_messaging.api import send

REMINDER_EVENT = "regulator_submission.reminder"
OVERDUE_EVENT = "regulator_submission.overdue"
ESCALATION_EVENT = "regulator_submission.escalation"
PRINCIPAL_POSITION = "PRINCIPAL"
OPEN_STATUS = "Pending"


def due_date(basis, period_end, month, day, days_after):
	"""The due date of a return for the period ending `period_end` under the type's rule."""
	period_end = getdate(period_end)
	if basis == "Days After Period End":
		return frappe.utils.add_days(period_end, cint(days_after))
	if basis != "Fixed Date Each Year":
		frappe.throw(_("Unknown due basis {0}.").format(frappe.bold(basis)))
	month, day = cint(month), cint(day)
	if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(2024, month)[1]:  # 2024: a leap year, so 29 Feb is allowed
		frappe.throw(_("Enter a valid due month and day."))
	for year in (period_end.year, period_end.year + 1):
		candidate = datetime.date(year, month, min(day, calendar.monthrange(year, month)[1]))
		if candidate >= period_end:
			return candidate


def reminder_offsets(text):
	"""'30, 7,1' -> [30, 7, 1]: days before the due date, nearest last."""
	offsets = []
	for part in (text or "").split(","):
		part = part.strip()
		if not part:
			continue
		if not part.isdigit():
			frappe.throw(_("Reminder days must be whole numbers separated by commas; {0} is not.").format(frappe.bold(part)))
		offsets.append(int(part))
	return sorted(set(offsets), reverse=True)


def stage(due, on_date, offsets):
	"""('reminder', days before) on a reminder day, ('overdue', days late) after the due date, else None."""
	days_left = date_diff(due, on_date)
	if days_left < 0:
		return "overdue", -days_left
	return ("reminder", days_left) if days_left in offsets else None


def principals(submission):
	"""Users holding the Principal position of the submission's company."""
	from campus.campus_platform.approver_resolution import resolve_approvers

	return resolve_approvers("Position", PRINCIPAL_POSITION, submission, "company")


def send_reminders(on_date=None):
	"""Scheduler entry point (daily). Returns the number of submissions messaged about."""
	on_date = getdate(on_date or today())
	count = 0
	for row in frappe.get_all("Regulator Submission", {"status": OPEN_STATUS}, ["name", "due_date", "submission_type"]):
		offsets = reminder_offsets(frappe.get_cached_value("Regulator Submission Type", row.submission_type, "reminder_days"))
		due_stage = stage(row.due_date, on_date, offsets)
		if not due_stage:
			continue
		try:
			notify(frappe.get_doc("Regulator Submission", row.name), on_date, *due_stage)
			count += 1
		except Exception:
			frappe.log_error(title=f"Regulator submission reminder failed for {row.name}")  # no context: keep the rest going
	return count


def notify(submission, on_date, kind, days):
	owner = f"Employee:{submission.owner_employee}"
	if kind == "reminder":
		send(REMINDER_EVENT, submission, [owner], context={"days": days, "dedupe_token": f"{days}d"})
		return
	year, week, _day = on_date.isocalendar()
	context = {"days": days, "dedupe_token": f"{year}-W{week}"}
	send(OVERDUE_EVENT, submission, [owner], context=context)
	send(ESCALATION_EVENT, submission, [f"User:{user}" for user in principals(submission)], context=context)
