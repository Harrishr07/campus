"""M16-02 Send one template to many recipients through the bulk runner (broadcasts and circulars).

The handler only creates Message Logs through `api.send` (DB-only, never commits; dispatch jobs are queued
after the chunk commits), and `send` is idempotent per (event, document, recipient, channel), so a resumed
or repeated run never messages anybody twice.
"""

import json

import frappe

from campus.campus_messaging.api import send
from campus.campus_platform.bulk import run_bulk

HANDLER = "campus.campus_messaging.bulk_send.send_to_recipient"


def start(run_type, event_key, doc, recipients, context=None):
	"""Queue a bulk run sending `event_key` about `doc` to `recipients`; returns the Bulk Run name (None if empty)."""
	if not recipients:
		return None
	parameters = {"event_key": event_key, "doctype": doc.doctype, "name": doc.name, "context": context or {}}
	return run_bulk(run_type, recipients, HANDLER, parameters=parameters)


def send_to_recipient(recipient, run):
	parameters = json.loads(run.parameters)
	doc = frappe.get_doc(parameters["doctype"], parameters["name"])
	send(parameters["event_key"], doc, [recipient], parameters["context"], now=False)
