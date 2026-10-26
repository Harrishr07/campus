"""M04-10 The document-pending reminder prints a temporary clearance's due date. Seeded bodies still holding the
first seed text get the new text; a body an administrator edited is left alone. Re-runnable."""

import frappe

from campus.campus_messaging.setup import DOCUMENT_PENDING_EN, DOCUMENT_PENDING_TA

FIRST_SEED = {
	"en": (
		"Your admission is waiting for these documents: {{ context.documents or '' }}. Please submit them to the college office.",
		DOCUMENT_PENDING_EN,
	),
	"ta": (
		"உங்கள் சேர்க்கைக்கு இந்த ஆவணங்கள் தேவை: {{ context.documents or '' }}. கல்லூரி அலுவலகத்தில் சமர்ப்பிக்கவும்.",
		DOCUMENT_PENDING_TA,
	),
}


def execute():
	for language, (old, new) in FIRST_SEED.items():
		frappe.db.set_value(
			"Message Template Body",
			{
				"parent": "admission.document_pending",
				"parenttype": "Message Template",
				"language": language,
				"body": old,
			},
			"body",
			new,
		)
	frappe.clear_document_cache("Message Template", "admission.document_pending")
