"""M17-03 Single notification entry point for campus platform events.

Sends a desk notification (Notification Log), which also emails the user when their notification
settings allow. P1-T10 replaces the body with a call to the messaging bus; callers stay unchanged.
"""

import frappe
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification


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
