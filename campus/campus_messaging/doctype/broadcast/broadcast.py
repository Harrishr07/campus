"""M16-02 Broadcast: one template sent to everyone an Audience Rule addresses.

Flow: Draft -> (Pending Approval when an Approval Policy matches) -> submit -> Scheduled (future
`schedule_at`) or Sending -> Sent. Releasing resolves the audience, then hands it to the bulk runner, which
creates one Message Log per recipient through `api.send` (consent, quiet hours and channel fallback apply).
Counts are derived from the Message Logs, so they stay true while delivery proceeds.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from campus.campus_messaging import audience, bulk_send
from campus.campus_platform.approvals import ApprovableDocument

DRAFT, PENDING, SCHEDULED, SENDING, SENT, FAILED = (
	"Draft",
	"Pending Approval",
	"Scheduled",
	"Sending",
	"Sent",
	"Failed",
)
RELEASABLE = (DRAFT, PENDING, SCHEDULED)
RUN_FINISHED = ("Completed", "Completed with errors")
ACCEPTED = ("Queued", "Scheduled", "Sent", "Delivered", "Read")


class Broadcast(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		rule = frappe.get_doc("Audience Rule", self.audience_rule)
		if rule.company != self.company:
			frappe.throw(_("Audience Rule {0} belongs to {1}, not {2}.").format(rule.name, rule.company, self.company))
		audience.ensure_available(rule)
		if not frappe.db.get_value("Message Template", self.message_template, "enabled"):
			frappe.throw(_("Message Template {0} is disabled.").format(self.message_template))
		self.context_values()

	def context_values(self):
		"""The template context as a dict (empty when none); must be a JSON object."""
		try:
			values = json.loads(self.context) if self.context else {}
		except ValueError:
			frappe.throw(_("Context must be valid JSON."))
		if not isinstance(values, dict):
			frappe.throw(_("Context must be a JSON object."))
		return values

	def on_submit(self):
		if self.schedule_at and get_datetime(self.schedule_at) > now_datetime():
			self.db_set("status", SCHEDULED)
		else:
			release(self.name)

	def before_cancel(self):
		if frappe.db.get_value("Broadcast", self.name, "status") == SENDING:
			frappe.throw(_("A broadcast that is being sent cannot be cancelled."))


def sync_approval_status(request, method=None):
	"""Approval Request hook: show Pending Approval while a Broadcast awaits approval, Draft after a return/reject."""
	if request.reference_doctype != "Broadcast" or not frappe.db.exists("Broadcast", request.reference_name):
		return
	if frappe.db.get_value("Broadcast", request.reference_name, "docstatus") != 0:
		return
	status = {"Pending": PENDING, "Returned": DRAFT, "Rejected": DRAFT}.get(request.status)
	if status:
		frappe.db.set_value("Broadcast", request.reference_name, "status", status, update_modified=False)


def release(name):
	"""Resolve the audience and queue the send, exactly once per submitted Broadcast."""
	docstatus, status = frappe.db.get_value("Broadcast", name, ["docstatus", "status"], for_update=True)
	if docstatus != 1 or status not in RELEASABLE:
		return
	broadcast = frappe.get_doc("Broadcast", name)
	recipients = audience.resolve(broadcast.audience_rule)
	run = bulk_send.start(
		f"Broadcast {name}", broadcast.message_template, broadcast, recipients, broadcast.context_values()
	)
	broadcast.db_set(
		{"status": SENDING if run else SENT, "bulk_run": run, "recipients_count": len(recipients)},
		update_modified=False,
	)


def release_due():
	"""Scheduler: release Scheduled broadcasts whose time has come, then close finished ones."""
	due = frappe.get_all(
		"Broadcast",
		filters={"docstatus": 1, "status": SCHEDULED, "schedule_at": ["<=", now_datetime()]},
		pluck="name",
	)
	for name in due:
		try:
			release(name)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Broadcast {name} could not be released")
			frappe.db.set_value("Broadcast", name, "status", FAILED, update_modified=False)
		frappe.db.commit()  # one release per transaction, so a failure cannot undo the others
	for name in frappe.get_all("Broadcast", filters={"docstatus": 1, "status": SENDING}, pluck="name"):
		refresh_status(name)
		frappe.db.commit()


@frappe.whitelist()
def refresh_status(name):
	"""Recount the broadcast from its Message Logs and follow its Bulk Run: Sending becomes Sent, or Failed if the run failed."""
	broadcast = frappe.get_doc("Broadcast", name)
	broadcast.check_permission("read")
	if broadcast.docstatus != 1 or broadcast.status not in (SENDING, SENT, FAILED):
		return broadcast.status
	run = frappe.db.get_value("Bulk Run", broadcast.bulk_run, ["status", "failed"], as_dict=True) if broadcast.bulk_run else None
	counts = delivery_counts(broadcast, run.failed if run else 0)
	status = broadcast.status
	if status in (SENDING, FAILED) and run:  # a resumed Failed run recovers
		status = SENT if run.status in RUN_FINISHED else FAILED if run.status == "Failed" else SENDING
	broadcast.db_set({**counts, "status": status}, update_modified=False)
	return status


def delivery_counts(broadcast, run_failures):
	"""Per recipient: queued if any attempt was accepted, else failed if any failed, else skipped."""
	by_recipient = {}
	logs = frappe.get_all(
		"Message Log",
		filters={"reference_doctype": "Broadcast", "reference_name": broadcast.name, "event_key": broadcast.message_template},
		fields=["recipient", "status"],
	)
	for log in logs:
		by_recipient.setdefault(log.recipient, set()).add(log.status)
	queued = sum(1 for s in by_recipient.values() if s & set(ACCEPTED))
	failed_logs = sum(1 for s in by_recipient.values() if not s & set(ACCEPTED) and "Failed" in s)
	skipped = len(by_recipient) - queued - failed_logs
	return {"queued_count": queued, "skipped_count": skipped, "failed_count": failed_logs + run_failures}
