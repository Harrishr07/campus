"""M05-11 Student record correction rules (pure): which fields each category may correct, who may raise it, which
categories need the higher approver, and the fields locked against direct desk edits. No database access."""

PERSONAL, CONTACT, GUARDIAN = "Personal", "Contact", "Guardian"
IDENTITY, ACADEMIC = "Identity Document", "Academic Identifier"

# category -> (DocType the field belongs to, correctable fieldnames)
CATEGORIES = {
	PERSONAL: ("Student", ("first_name", "middle_name", "last_name", "date_of_birth", "gender", "blood_group", "nationality")),
	CONTACT: (
		"Student",
		("student_email_id", "student_mobile_number", "address_line_1", "address_line_2", "pincode", "city", "state", "country"),
	),
	GUARDIAN: ("Guardian", ("guardian_name", "email_address", "mobile_number", "alternate_number", "occupation")),
	IDENTITY: ("Student", ("oc_aadhaar",)),
	ACADEMIC: ("Student", ("oc_register_no", "oc_roll_no")),
}
PORTAL_CATEGORIES = (PERSONAL, CONTACT, GUARDIAN)  # a student or guardian may raise these; the office raises any
HIGHER_CATEGORIES = (IDENTITY, ACADEMIC)  # need the Principal after the first approver
EVIDENCE_FREE = (CONTACT,)  # every other category needs an evidence file
MASK_PREFIX = "XXXX-XXXX-"


def target_doctype(category):
	return CATEGORIES[category][0] if category in CATEGORIES else None


def allowed_fields(category):
	return CATEGORIES[category][1] if category in CATEGORIES else ()


def refusal(category, fieldname, portal=False):
	"""Why `fieldname` cannot be corrected under `category` (a code), or None."""
	if category not in CATEGORIES:
		return "category"
	if fieldname not in allowed_fields(category):
		return "field"
	if portal and category not in PORTAL_CATEGORIES:
		return "portal"
	return None


def needs_evidence(category):
	return category not in EVIDENCE_FREE


def locked_fields(text, allowed):
	"""Fieldnames listed one per line in `text`, kept to the correctable ones (a lock on any other field has no
	workflow behind it)."""
	listed = [line.strip() for line in (text or "").replace(",", "\n").splitlines()]
	return [name for name in dict.fromkeys(listed) if name in allowed]


def student_fields():
	"""Every correctable field of the Student itself (the ones a lock can cover)."""
	return {field for doctype, fields in CATEGORIES.values() if doctype == "Student" for field in fields}
