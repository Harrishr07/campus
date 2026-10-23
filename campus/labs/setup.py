"""M12-05 Seeds for labs: the calibration notice Message Template and the notice days."""

import frappe

NOTICE_DAYS = 15
TEMPLATE = (
	"lab.calibration_due",
	"Calibration due: {{ context.asset_name }} ({{ context.laboratory }})",
	"{{ context.task }} of {{ context.asset_name }} ({{ context.asset }}) in {{ context.laboratory }} is due on "
	"{{ frappe.format(context.due_date, {'fieldtype': 'Date'}) }}, in {{ context.days }} day(s). "
	"Please arrange it and record it as done.",
)


def setup_labs():
	seed_template()
	if not frappe.db.get_single_value("Laboratory Settings", "calibration_notice_days"):
		frappe.db.set_single_value("Laboratory Settings", "calibration_notice_days", NOTICE_DAYS)


def seed_template():
	event_key, subject, body = TEMPLATE
	if frappe.db.exists("Message Template", event_key):
		return
	frappe.get_doc(
		{
			"doctype": "Message Template", "event_key": event_key, "purpose": "transactional",
			"channels": [{"channel": "email"}, {"channel": "whatsapp"}, {"channel": "sms"}],
			"bodies": [{"language": "en", "subject": subject, "body": body}],
		}
	).insert(ignore_permissions=True)  # fmt: skip
