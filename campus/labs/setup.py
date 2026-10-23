"""M12-05 Seeds for labs: the calibration notice Message Template, the notice days and the Lab In-charge's read of
the ERPNext Asset records the lab equipment reports are built on."""

import frappe

NOTICE_DAYS = 15
TEMPLATE = (
	"lab.calibration_due",
	"Calibration due: {{ context.asset_name }} ({{ context.laboratory }})",
	"{{ context.task }} of {{ context.asset_name }} ({{ context.asset }}) in {{ context.laboratory }} is due on "
	"{{ frappe.format(context.due_date, {'fieldtype': 'Date'}) }}, in {{ context.days }} day(s). "
	"Please arrange it and record it as done.",
)


# Custom DocPerm (ERPNext's JSON is never edited); company User Permissions scope the rows as on every company record.
LAB_ROLE = "Lab In-charge"
LAB_ASSET_DOCTYPES = ("Asset", "Asset Maintenance")


def setup_labs():
	seed_template()
	grant_lab_asset_read()
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


def grant_lab_asset_read():
	"""Read and report on the lab's assets (Labs > Equipment). Added when the role has no rule on the DocType, so a
	rule the college edited stays as it is."""
	from frappe.core.doctype.custom_docperm.custom_docperm import update_custom_docperm
	from frappe.permissions import add_permission

	if not frappe.db.exists("Role", LAB_ROLE):  # seeded with the No Dues offices (campus_finance)
		return
	for doctype in LAB_ASSET_DOCTYPES:
		if not frappe.db.exists("DocType", doctype) or frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": LAB_ROLE}):
			continue
		name = add_permission(doctype, LAB_ROLE, 0)  # copies the standard DocPerms first, so none is lost
		update_custom_docperm(name, {"read": 1, "report": 1, "export": 0})
