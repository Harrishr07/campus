"""X-03 / R-07: Credit Recognition joins the mandatory approval list on existing sites, with its seeded policy (a Dean
Academics of the student's college), so a recognition that clears a degree requirement is never submitted unapproved.
Only this document type is added: the college's other edits to the list stand. DML only."""

import frappe

from campus.campus_platform.mandatory_approval import ROW_DOCTYPE, SETTINGS_FIELD, uses_approval_engine
from campus.curriculum.recognitions import DOCTYPE, seed_recognition_policy


def execute():
	if not frappe.db.exists("DocType", DOCTYPE) or not uses_approval_engine(DOCTYPE):
		return
	seed_recognition_policy()
	if frappe.db.exists(ROW_DOCTYPE, {"parenttype": "Campus Settings", "parentfield": SETTINGS_FIELD, "document_type": DOCTYPE}):
		return
	settings = frappe.get_doc("Campus Settings")
	settings.append(SETTINGS_FIELD, {"document_type": DOCTYPE})
	settings.flags.ignore_permissions = True
	settings.save()
