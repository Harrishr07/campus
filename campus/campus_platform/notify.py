"""M17-03 Single notification entry point for campus platform events.

Always sends a desk notification (Notification Log), which also emails the user when their notification
settings allow. When the "approval.notification" Message Template exists, the message is also sent through
the messaging bus (WhatsApp/SMS per template and consent) to each user.
"""

import hashlib

import frappe
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

EVENT_KEY = "approval.notification"
SAVEPOINT = "notify_messaging"


def notify(users, subject, message, doc):
	users = [u for u in dict.fromkeys(users or []) if u]
	if not users:
		return
	enqueue_create_notification(
		users,
		{
			"type": "Alert",
			"subject": subject,
			"email_content": message,
			"document_type": doc.doctype,
			"document_name": doc.name,
			"from_user": frappe.session.user,
		},
	)
	_send_via_messaging(users, subject, message, doc)


def _send_via_messaging(users, subject, message, doc):
	"""Best effort: a messaging problem must never break the approval transition that triggered it."""
	if not frappe.db.exists("Message Template", {"event_key": EVENT_KEY, "enabled": 1}):
		return
	from campus.campus_messaging.api import send

	token = hashlib.sha1(f"{subject}\n{message}".encode()).hexdigest()
	frappe.db.savepoint(SAVEPOINT)
	try:
		send(
			EVENT_KEY,
			doc,
			[f"User:{u}" for u in users],
			{"subject": subject, "message": message, "dedupe_token": token},
		)
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.log_error(title="Approval notification via messaging failed")
