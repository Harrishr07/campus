"""M01-08 / M01-09 Seeds for the official document register and the AISHE export: the expiry alert Message Templates, the
alert days, and the placeholder AISHE Layout (never overwriting what the college edited)."""

import frappe

from campus.iqac.aishe import PLACEHOLDER_LAYOUT, SECTIONS

LINK = "{{ doc.document_type }} of {{ doc.authority }} ({{ doc.reference_no }})"
VALID_TO = "{{ frappe.format(doc.valid_to, {'fieldtype': 'Date'}) }}"
TEMPLATES = [
	(
		"official_document.expiring", "Expiring: {{ doc.authority }} {{ doc.document_type }}",
		LINK + " is valid until " + VALID_TO + ", in {{ context.days }} day(s). Please renew it and record the new document.",
	),
	(
		"official_document.expired", "Expired: {{ doc.authority }} {{ doc.document_type }}",
		LINK + " was valid until " + VALID_TO + " and has expired. Please record its renewal.",
	),
]  # fmt: skip
ALERT_DAYS = "90, 30, 7"
LAYOUT_NOTE = "Placeholder layout - the official AISHE template was not available; replace the mappings with the official layout."


def seed_official_register():
	seed_templates()
	if not frappe.db.get_single_value("Official Document Setting", "alert_days"):
		frappe.db.set_single_value("Official Document Setting", "alert_days", ALERT_DAYS)
	seed_aishe_layout()


def seed_templates():
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


def seed_aishe_layout():
	if frappe.db.exists("AISHE Layout", PLACEHOLDER_LAYOUT):
		return
	frappe.get_doc(
		{
			"doctype": "AISHE Layout",
			"layout_name": PLACEHOLDER_LAYOUT,
			"is_placeholder": 1,
			"description": LAYOUT_NOTE,
			"sections": [{"section": section, "sheet": section, "first_cell": "A3"} for section in SECTIONS],
		}
	).insert(ignore_permissions=True)
