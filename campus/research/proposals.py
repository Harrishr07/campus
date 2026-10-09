"""M08-02 Research proposal deadline reminders: every day, the PI of each proposal not yet submitted to the agency
(draft, under review or internally approved) is messaged from the call's `reminder_days` before its deadline up to the
deadline day. One message per proposal per day (the day is the messaging dedupe token). A draft whose latest internal
review was Rejected gets no more reminders."""

import frappe
from frappe.utils import date_diff, getdate, today

from campus.campus_messaging.api import send
from campus.campus_platform.api import latest_request
from campus.research.setup import REMINDER_EVENT

OPEN_STATUSES = ("Draft", "Approved")


def reminder_due(deadline, on_date, reminder_days):
	"""True when `on_date` falls within `reminder_days` days before `deadline`, the deadline day included."""
	return 0 <= date_diff(deadline, on_date) <= (reminder_days or 0)


def send_deadline_reminders(on_date=None):
	"""Scheduler entry point (daily). Returns the number of proposals reminded."""
	on_date = getdate(on_date or today())
	due = [
		row
		for row in open_proposals(on_date)
		if reminder_due(row.deadline, on_date, row.reminder_days) and not rejected_internally(row.name)
	]
	for row in due:
		try:
			proposal = frappe.get_doc("Research Proposal", row.name)
			send(
				REMINDER_EVENT,
				proposal,
				[f"Employee:{proposal.principal_investigator}"],
				context={"deadline": row.deadline, "dedupe_token": str(on_date)},
			)
		except Exception:
			frappe.log_error(title=f"Research proposal deadline reminder failed for {row.name}")  # keep the rest going
	return len(due)


def rejected_internally(proposal):
	request = latest_request(frappe._dict(doctype="Research Proposal", name=proposal))
	return bool(request and request.status == "Rejected")


def open_proposals(on_date):
	"""Open proposals whose call's current deadline is today or later, with the call's reminder window."""
	proposal, call = frappe.qb.DocType("Research Proposal"), frappe.qb.DocType("Research Call")
	return (
		frappe.qb.from_(proposal)
		.join(call)
		.on(call.name == proposal.research_call)
		.select(proposal.name, call.deadline, call.reminder_days)
		.where(proposal.docstatus < 2)
		.where(proposal.status.isin(OPEN_STATUSES))
		.where(call.deadline >= on_date)
		.run(as_dict=True)
	)
