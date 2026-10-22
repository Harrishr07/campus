"""M01-06 Message Templates for the regulator submission reminder, overdue notice and Principal escalation (never overwriting)."""

import frappe

LINK = "{{ doc.submission_type }} for the period ending {{ frappe.format(doc.period_end, {'fieldtype': 'Date'}) }}"
TEMPLATES = [
	(
		"regulator_submission.reminder", "Due soon: {{ doc.submission_type }}",
		LINK + " is due on {{ frappe.format(doc.due_date, {'fieldtype': 'Date'}) }}, in {{ context.days }} day(s). Please file it and record the acknowledgement.",
	),
	(
		"regulator_submission.overdue", "Overdue: {{ doc.submission_type }}",
		LINK + " was due on {{ frappe.format(doc.due_date, {'fieldtype': 'Date'}) }} and is {{ context.days }} day(s) late. Please file it now.",
	),
	(
		"regulator_submission.escalation", "Overdue return: {{ doc.submission_type }}",
		LINK + " owned by {{ doc.owner_employee }} was due on {{ frappe.format(doc.due_date, {'fieldtype': 'Date'}) }} and is {{ context.days }} day(s) late.",
	),
]  # fmt: skip


def seed_regulator_templates():
	for event_key, subject, body in TEMPLATES:
		if frappe.db.exists("Message Template", event_key):
			continue
		frappe.get_doc(
			{
				"doctype": "Message Template", "event_key": event_key, "purpose": "transactional",
				"channels": [{"channel": "email"}, {"channel": "whatsapp"}, {"channel": "sms"}],
				"bodies": [{"language": "en", "subject": subject, "body": body}],
			}
		).insert(ignore_permissions=True)  # fmt: skip
