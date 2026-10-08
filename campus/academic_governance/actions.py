"""M02-03 Meeting action follow-up: a weekly message to the owner of every action item still open past its due date."""

import frappe
from frappe.utils import getdate, today

from campus.campus_messaging.api import send

OVERDUE_EVENT = "meeting_action.overdue"
OPEN_STATUSES = ["Open", "In Progress"]


def notify_overdue(on_date=None):
	"""Message the owners of overdue open items; one message per item per ISO week. Returns the items found."""
	on_date = getdate(on_date or today())
	year, week, _day = on_date.isocalendar()
	items = frappe.get_all("Meeting Action Item", {"status": ["in", OPEN_STATUSES], "due_date": ["<", on_date]}, pluck="name")
	for name in items:
		item = frappe.get_doc("Meeting Action Item", name)
		send(OVERDUE_EVENT, item, [f"Employee:{item.responsible}"], context={"dedupe_token": f"{year}-W{week}"})
	return len(items)
