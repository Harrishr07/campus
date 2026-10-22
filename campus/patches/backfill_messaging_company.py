"""M16 Fill `company` on Message Logs and Communication Consents created before the field existed. Re-runnable."""

import frappe

from campus.campus_messaging.scope import company_of


def execute():
	frappe.reload_doc("campus_messaging", "doctype", "message_log")
	frappe.reload_doc("campus_messaging", "doctype", "communication_consent")
	for log in frappe.get_all(
		"Message Log",
		filters={"company": ["in", ["", None]]},
		fields=["name", "reference_doctype", "reference_name", "recipient"],
		limit=0,
	):
		party_type, _sep, party = (log.recipient or "").partition(":")
		company = company_of(log.reference_doctype, log.reference_name) or company_of(party_type, party)
		if company:
			frappe.db.set_value("Message Log", log.name, "company", company, update_modified=False)
	for consent in frappe.get_all(
		"Communication Consent", filters={"company": ["in", ["", None]]}, fields=["name", "party_type", "party"], limit=0
	):
		company = company_of(consent.party_type, consent.party)
		if company:
			frappe.db.set_value("Communication Consent", consent.name, "company", company, update_modified=False)
