"""M16-01 Recipient resolution.

Recipient formats accepted by `api.send` (all resolve to the same dict):
  {"doctype": "Guardian", "name": "GRD-0001"}   dict form (Student, Guardian, Employee, User)
  "Guardian:GRD-0001" / "User:a@b.com"           "<Doctype>:<name>" string
  "phone:+919876543210"                          bare number (no party, so no consent record, no language)
"""

import frappe
from frappe import _

DEFAULT_LANGUAGE = "en"

# doctype -> (email fields in preference order, mobile fields, user field, language field, display name field)
SOURCES = {
	"Student": (["student_email_id"], ["student_mobile_number"], "user", "oc_language", "student_name"),
	"Guardian": (["email_address"], ["mobile_number"], "user", "oc_language", "guardian_name"),
	"Employee": (["prefered_email", "company_email", "personal_email"], ["cell_number"], "user_id", "oc_language", "employee_name"),
	"User": (["email"], ["mobile_no", "phone"], "name", "language", "full_name"),
}


def parse(recipient):
	"""Normalise a recipient to (doctype, name); doctype is "phone" for bare numbers."""
	if isinstance(recipient, dict):
		return recipient.get("doctype"), recipient.get("name")
	if isinstance(recipient, str) and ":" in recipient:
		doctype, _sep, name = recipient.partition(":")
		return doctype.strip(), name.strip()
	frappe.throw(_("Unsupported recipient: {0}").format(recipient))


def resolve(recipient):
	"""Return {key, party_type, party, email, mobile, user, language, display_name} for one recipient."""
	doctype, name = parse(recipient)
	if doctype == "phone":
		return _entry(f"phone:{name}", None, None, None, name, None, DEFAULT_LANGUAGE)
	if doctype not in SOURCES or not name:
		frappe.throw(_("Unsupported recipient: {0}").format(recipient))
	emails, mobiles, user_field, language_field, name_field = SOURCES[doctype]
	row = frappe.db.get_value(doctype, name, [*emails, *mobiles, user_field, language_field, name_field], as_dict=True)
	if not row:
		frappe.throw(_("{0} {1} not found").format(_(doctype), name))
	return _entry(
		f"{doctype}:{name}",
		doctype,
		name,
		next((row[f] for f in emails if row[f]), None),
		next((row[f] for f in mobiles if row[f]), None),
		row[user_field],
		_language(row[language_field]),
		row[name_field] or name,
	)


def _entry(key, party_type, party, email, mobile, user, language, display_name=None):
	return {
		"key": key,
		"party_type": party_type,
		"party": party,
		"email": email,
		"mobile": mobile,
		"user": user,
		"language": language,
		"display_name": display_name,
	}


def _language(value):
	return (value or DEFAULT_LANGUAGE).split("-")[0].lower()
