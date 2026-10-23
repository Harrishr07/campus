"""P3-T20 / R-07: Consultancy Revenue Share joins the mandatory approval list on existing sites, with its seeded policy
(Accounts, then the Principal) so shares keep being approvable. Only this document type is added: the college's other
edits to the list stand. DML only."""

import frappe

from campus.campus_platform.mandatory_approval import ROW_DOCTYPE, SETTINGS_FIELD, uses_approval_engine
from campus.research.setup import seed_share_policy

DOCTYPE = "Consultancy Revenue Share"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE) or not uses_approval_engine(DOCTYPE):
		return
	seed_share_policy()
	if frappe.db.exists(ROW_DOCTYPE, {"parenttype": "Campus Settings", "parentfield": SETTINGS_FIELD, "document_type": DOCTYPE}):
		return
	settings = frappe.get_doc("Campus Settings")
	settings.append(SETTINGS_FIELD, {"document_type": DOCTYPE})
	settings.flags.ignore_permissions = True
	settings.save()
