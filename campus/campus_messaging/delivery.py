"""M16-01 Message Log lifecycle: create attempts, dispatch them with fallback, apply status updates.

Contract (safe to run as a bulk-runner handler or a queued job): nothing here commits, and
`dispatch_log` only sends a log that is still Queued, so a retried job never sends twice.
"""

import hashlib
import json

import frappe
from frappe.utils import now_datetime

from campus.campus_messaging.channels import ChannelError, send_via

NO_KEY_STATUSES = ("Failed", "Skipped")  # these attempts do not hold the idempotency key
SAVEPOINT = "message_attempt"
# Status rank: a webhook may only move a log forward (Sent -> Delivered -> Read).
RANK = {"Queued": 0, "Scheduled": 0, "Sent": 1, "Delivered": 2, "Read": 3}


def idempotency_key(event_key, doc, recipient, channel, token=""):
	raw = "\n".join([event_key, f"{doc.doctype}:{doc.name}", recipient, channel, token or ""])
	return hashlib.sha1(raw.encode()).hexdigest()


def existing_logs(event_key, doc, recipient, token=""):
	"""Logs of earlier attempts that block a repeat send: any attempt that did not fail or get skipped."""
	return frappe.get_all(
		"Message Log",
		filters={
			"event_key": event_key,
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"recipient": recipient,
			"dedupe_token": token or "",
			"status": ("not in", NO_KEY_STATUSES),
		},
		pluck="name",
		order_by="creation asc",
	)


def create_log(template, doc, entry, channel, address, subject, message, variables, status="Queued", token="", **extra):
	"""Insert a Message Log; returns None when another live attempt already holds its idempotency key."""
	key = None if status in NO_KEY_STATUSES else idempotency_key(template.event_key, doc, entry["key"], channel, token)
	log = frappe.get_doc(
		{
			"doctype": "Message Log",
			"event_key": template.event_key,
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"recipient": entry["key"],
			"language": entry["language"],
			"channel": channel,
			"address": address,
			"status": status,
			"dedupe_token": token or "",
			"idempotency_key": key,
			"subject": subject,
			"message": message,
			"variables": json.dumps(variables),
			**extra,
		}
	)
	try:
		frappe.db.savepoint(SAVEPOINT)
		log.insert(ignore_permissions=True)
	except frappe.UniqueValidationError:
		frappe.db.rollback(save_point=SAVEPOINT)
		return None
	return log


def dispatch_log(name):
	"""Send a Queued log; on failure log it and try the remaining channels in order."""
	log = _claim(name)
	while log:
		if _attempt(log):
			return
		log = _next_attempt(log)


def _claim(name):
	status = frappe.db.get_value("Message Log", name, "status", for_update=True)
	return frappe.get_doc("Message Log", name) if status == "Queued" else None


def _attempt(log):
	template = frappe.get_cached_doc("Message Template", log.event_key)
	frappe.db.savepoint(SAVEPOINT)
	try:
		provider_id = send_via(log.channel, log, template)
	except Exception as e:
		frappe.db.rollback(save_point=SAVEPOINT)
		if not isinstance(e, ChannelError):
			frappe.log_error(title="Message dispatch failed")
		log.db_set({"status": "Failed", "error": str(e)[:1000], "idempotency_key": None})
		return False
	log.db_set({"status": "Sent", "provider_id": provider_id})
	return True


def _next_attempt(failed):
	"""Queue the next channel from the failed log's fallback list (each item {"channel", "address"})."""
	remaining = json.loads(failed.fallback_channels or "[]")
	template = frappe.get_cached_doc("Message Template", failed.event_key)
	doc = frappe._dict(doctype=failed.reference_doctype, name=failed.reference_name)
	entry = {"key": failed.recipient, "language": failed.language}
	while remaining:
		(channel, address), remaining = (remaining[0]["channel"], remaining[0]["address"]), remaining[1:]
		log = create_log(
			template,
			doc,
			entry,
			channel,
			address,
			failed.subject,
			failed.message,
			json.loads(failed.variables or "[]"),
			token=failed.dedupe_token,
			fallback_channels=json.dumps(remaining),
		)
		if log:
			return log
	return None


def dispatch_due():
	"""Scheduler job (every 15 minutes): release Scheduled logs whose quiet hours have ended."""
	due = frappe.get_all(
		"Message Log",
		filters={"status": "Scheduled", "send_after": ("<=", now_datetime())},
		pluck="name",
		order_by="send_after asc",
	)
	for name in due:
		frappe.db.set_value("Message Log", name, "status", "Queued", update_modified=False)
		dispatch_log(name)


def sync_whatsapp_status(doc, method=None):
	"""doc_events hook on WhatsApp Message: delivery webhooks update the matching Message Log."""
	status = {"sent": "Sent", "delivered": "Delivered", "read": "Read", "failed": "Failed"}.get(
		(doc.status or "").lower()
	)
	if not status or not doc.message_id:
		return
	log = frappe.db.get_value(
		"Message Log",
		{"channel": "whatsapp", "provider_id": doc.message_id},
		["name", "status"],
		as_dict=True,
	)
	if not log:
		return
	if status == "Failed":
		frappe.db.set_value(
			"Message Log", log.name, {"status": "Failed", "error": "Failed after hand-off (provider webhook)", "idempotency_key": None}
		)
	elif RANK.get(status, 0) > RANK.get(log.status, 0):
		frappe.db.set_value("Message Log", log.name, "status", status)
