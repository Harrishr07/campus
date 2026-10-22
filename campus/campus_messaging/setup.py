"""M16-01 Messaging setup run on install and migrate: language fields, default settings, seed templates."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Campus Messaging"
LANGUAGE_FIELD = {
	"fieldname": "oc_language",
	"label": "Preferred Language",
	"fieldtype": "Select",
	"options": "en\nta",
	"default": "en",
	"module": MODULE,
}
# doctype -> field to insert the language after
LANGUAGE_ANCHORS = {"Student": "student_mobile_number", "Guardian": "mobile_number", "Employee": "cell_number"}

SEED_TEMPLATES = [
	{
		"event_key": "fees.due",
		"purpose": "transactional",
		"urgent": 0,
		"channels": ["whatsapp", "sms", "email"],
		"bodies": {
			"en": ("Fee due", "Dear {{ recipient.display_name or 'Parent' }}, a fee of {{ context.amount or '' }} is due for {{ doc.name }}."),
			"ta": ("கட்டணம் நிலுவை", "அன்புள்ள {{ recipient.display_name or 'பெற்றோர்' }}, {{ doc.name }} க்கான கட்டணம் {{ context.amount or '' }} நிலுவையில் உள்ளது."),
		},
	},
	{
		"event_key": "approval.notification",
		"purpose": "transactional",
		"urgent": 1,
		"channels": ["whatsapp", "sms"],
		"bodies": {
			"en": ("{{ context.subject }}", "{{ context.subject }}: {{ context.message or '' }}"),
			"ta": ("{{ context.subject }}", "{{ context.subject }}: {{ context.message or '' }} (அங்கீகாரம் தேவை)"),
		},
	},
	{
		"event_key": "circular.published",
		"purpose": "transactional",
		"urgent": 0,
		"channels": ["whatsapp", "sms", "email"],
		"bodies": {
			"en": ("New circular: {{ doc.title }}", "A new circular has been published: {{ doc.title }}. Please log in to the portal to read it."),
			"ta": ("புதிய சுற்றறிக்கை: {{ doc.title }}", "புதிய சுற்றறிக்கை வெளியிடப்பட்டுள்ளது: {{ doc.title }}. படிக்க இணையதளத்தில் உள்நுழையவும்."),
		},
	},
	{
		"event_key": "admission.document_pending",
		"purpose": "transactional",
		"urgent": 0,
		"channels": ["whatsapp", "sms"],
		"bodies": {
			"en": ("Admission documents pending", "Your admission is waiting for these documents: {{ context.documents or '' }}. Please submit them to the college office."),
			"ta": ("சேர்க்கை ஆவணங்கள் நிலுவை", "உங்கள் சேர்க்கைக்கு இந்த ஆவணங்கள் தேவை: {{ context.documents or '' }}. கல்லூரி அலுவலகத்தில் சமர்ப்பிக்கவும்."),
		},
	},
	{
		"event_key": "admission.enquiry_ack",
		"purpose": "transactional",
		"urgent": 0,
		"channels": ["whatsapp"],
		"bodies": {
			"en": ("Enquiry received", "Dear {{ doc.lead_name }}, thank you for your admission enquiry. Our admission office will contact you shortly."),
			"ta": ("விசாரணை பெறப்பட்டது", "அன்புள்ள {{ doc.lead_name }}, உங்கள் சேர்க்கை விசாரணைக்கு நன்றி. எங்கள் சேர்க்கை அலுவலகம் விரைவில் உங்களை தொடர்பு கொள்ளும்."),
		},
	},
	{
		"event_key": "attendance.shortage",
		"purpose": "transactional",
		"urgent": 0,
		"channels": ["whatsapp", "sms", "email"],
		"bodies": {
			"en": ("Attendance shortage", "Dear {{ recipient.display_name or 'Parent' }}, attendance of {{ doc.name }} is {{ context.percentage or '' }}%, below the required level."),
			"ta": ("வருகைப் பற்றாக்குறை", "அன்புள்ள {{ recipient.display_name or 'பெற்றோர்' }}, {{ doc.name }} வருகை {{ context.percentage or '' }}% ஆக குறைவாக உள்ளது."),
		},
	},
]


def setup_messaging():
	create_custom_fields(
		{dt: [{**LANGUAGE_FIELD, "insert_after": after}] for dt, after in LANGUAGE_ANCHORS.items()},
		update=True,
	)
	ensure_default_settings()
	seed_templates()


def ensure_default_settings():
	settings = frappe.get_single("Messaging Settings")
	if not settings.channel_order:
		for channel in ("whatsapp", "sms", "email", "push"):
			settings.append("channel_order", {"channel": channel})
		settings.save(ignore_permissions=True)


def seed_templates():
	"""Create the starter templates once; existing (possibly edited) templates are left alone."""
	for spec in SEED_TEMPLATES:
		if frappe.db.exists("Message Template", spec["event_key"]):
			continue
		frappe.get_doc(
			{
				"doctype": "Message Template",
				"event_key": spec["event_key"],
				"purpose": spec["purpose"],
				"urgent": spec["urgent"],
				"channels": [{"channel": c} for c in spec["channels"]],
				"bodies": [
					{"language": lang, "subject": subject, "body": body} for lang, (subject, body) in spec["bodies"].items()
				],
			}
		).insert(ignore_permissions=True)
