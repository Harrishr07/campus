"""M01-08 Official document register: the status rule, the superseded chain and the daily expiry alerts.

A document is Active through its last valid day, Expired after it, and Superseded once it names the document that replaced
it (that wins over the dates). Nothing is deleted: expired and superseded documents stay for history. Alerts go to the
Principal and the IQAC Coordinator of the college on the days of the Official Document Setting (90, 30 and 7 by default),
once per day mark; the day a document passes its last day it is marked Expired and they are told once. The day arithmetic is
the Regulator Submission reminder schedule (campus.iqac.regulator).
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

from campus.campus_messaging.api import send
from campus.iqac import regulator

EXPIRING_EVENT = "official_document.expiring"
EXPIRED_EVENT = "official_document.expired"
DEFAULT_ALERT_DAYS = "90, 30, 7"  # the default of the setting record, for a site that never saved it
DOCTYPE = "Official Document"


def document_status(valid_to, superseded_by, on_date=None):
	"""Superseded when a newer document replaced it, else Expired after the last valid day, else Active."""
	if superseded_by:
		return "Superseded"
	return "Expired" if getdate(on_date or today()) > getdate(valid_to) else "Active"


def alert_offsets(text):
	"""'90, 7,30' -> [90, 30, 7]: days before the last valid day."""
	return regulator.reminder_offsets(text)


def expiry_stage(valid_to, on_date, offsets):
	"""('reminder', days left) on an alert day, ('expired', days past) after the last valid day, else None."""
	due_stage = regulator.stage(valid_to, on_date, offsets)
	return ("expired", due_stage[1]) if due_stage and due_stage[0] == "overdue" else due_stage


# superseded chain


def check_successor(document):
	"""The superseding document is another document of the same company that does not lead back to this one."""
	successor = document.superseded_by
	if not successor:
		return
	if successor == document.name:
		frappe.throw(_("A document cannot supersede itself."))
	if frappe.db.get_value(DOCTYPE, successor, "company") != document.company:
		frappe.throw(_("{0} belongs to another company.").format(frappe.bold(successor)))
	if document.name in forward(successor):
		frappe.throw(
			_("{0} already leads back to {1}: the chain would loop.").format(
				frappe.bold(successor), frappe.bold(document.name)
			)
		)


def chain(name):
	"""The documents from the oldest one that leads to `name` to the current one, `name` among them."""
	names = [name]
	while True:
		older = frappe.db.get_value(DOCTYPE, {"superseded_by": names[0]}, "name", order_by="valid_from, name")
		if not older or older in names:
			break
		names.insert(0, older)
	return names[:-1] + forward(names[-1])


def forward(name):
	names = [name]
	while True:
		newer = frappe.db.get_value(DOCTYPE, names[-1], "superseded_by")
		if not newer or newer in names:
			return names
		names.append(newer)


def current(name):
	"""The document at the end of the chain of `name`."""
	return forward(name)[-1]


# daily alerts


def send_expiry_alerts(on_date=None):
	"""Scheduler entry point (daily). Returns the number of documents alerted about or marked Expired."""
	on_date = getdate(on_date or today())
	offsets = alert_offsets(
		frappe.db.get_single_value("Official Document Setting", "alert_days") or DEFAULT_ALERT_DAYS
	)
	count = 0
	for row in frappe.get_all(DOCTYPE, {"status": "Active"}, ["name", "valid_to"], order_by="valid_to, name"):
		due_stage = expiry_stage(row.valid_to, on_date, offsets)
		if not due_stage:
			continue
		try:
			alert(frappe.get_doc(DOCTYPE, row.name), *due_stage)
			count += 1
		except Exception:
			frappe.log_error(
				title=f"Official document alert failed for {row.name}"
			)  # no context: keep the rest going
	return count


def alert(document, kind, days):
	"""Tell the people, then (for an expiry) mark the document Expired, so a failed send is retried by the next run."""
	valid_to = str(document.valid_to)  # a renewal moves it, so the next expiry is alerted afresh
	if kind == "expired":
		event, context = EXPIRED_EVENT, {"days": days, "dedupe_token": f"expired-{valid_to}"}
	else:
		event, context = EXPIRING_EVENT, {"days": days, "dedupe_token": f"{days}d-{valid_to}"}
	people = recipients(document.company)
	if people:
		send(event, document, [f"Employee:{employee}" for employee in people], context=context)
	else:  # nobody to tell: say so, the run goes on
		frappe.logger("campus").warning(
			f"Official Document {document.name}: {event}, but {document.company} has no Principal or IQAC Coordinator on its Institution Profile"
		)
	if kind == "expired":
		document.db_set("status", "Expired", update_modified=False)


def recipients(company):
	"""The Principal and the IQAC Coordinator named on the Institution Profile of `company`."""
	row = frappe.db.get_value(
		"Institution Profile", {"company": company}, ["principal", "iqac_coordinator"], as_dict=True
	)
	return (
		list(dict.fromkeys(employee for employee in (row.principal, row.iqac_coordinator) if employee))
		if row
		else []
	)
