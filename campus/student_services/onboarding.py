"""M05-01 Student Onboarding: default templates, creation at admission, item ticking."""

import frappe

TEMPLATE = "Student Onboarding Template"
ONBOARDING = "Student Onboarding"

DEFAULT_ITEMS = [
	# code, title, mandatory, requires attachment
	("ID-CARD", "ID card", 1, 0),
	("LIBRARY-CARD", "Library card", 1, 0),
	("BUS-PASS", "Bus pass", 0, 0),
	("HOSTEL", "Hostel", 0, 0),
	("MENTOR", "Mentor assigned", 1, 0),
	("CODE-OF-CONDUCT", "Code of conduct acknowledgement", 1, 0),
	("ANTI-RAGGING", "Anti-ragging affidavit", 1, 1),
	("INDUCTION", "Induction programme", 1, 0),
]


def ensure_default_templates():
	"""One default template per Institution Profile company that has none. Idempotent."""
	for company in frappe.get_all("Institution Profile", pluck="company"):
		ensure_default_template(company)


def ensure_default_template(company):
	if frappe.db.exists(TEMPLATE, {"company": company, "is_default": 1}):
		return
	frappe.get_doc(
		{
			"doctype": TEMPLATE,
			"template_name": f"Student Onboarding - {company}",
			"company": company,
			"is_default": 1,
			"items": [
				{"item_code": code, "title": title, "mandatory": mandatory, "requires_attachment": attachment}
				for code, title, mandatory, attachment in DEFAULT_ITEMS
			],
		}
	).insert(ignore_permissions=True)


def seed_template_for_profile(doc, method=None):
	"""Institution Profile after_insert."""
	ensure_default_template(doc.company)


def create_for_student(student):
	"""The student's onboarding from their company's default template.

	Returns the existing one when there is one; None when the company has no default template. The caller
	(admission) is authorised, so permissions are not checked here.
	"""
	existing = frappe.db.get_value(ONBOARDING, {"student": student})
	if existing:
		return existing
	company = frappe.db.get_value("Student", student, "oc_company")
	template = company and frappe.db.get_value(TEMPLATE, {"company": company, "is_default": 1})
	if not template:
		return None
	items = frappe.get_all(
		"Student Onboarding Template Item",
		filters={"parent": template},
		fields=["item_code", "title", "mandatory", "requires_attachment"],
		order_by="idx",
	)
	doc = frappe.get_doc(
		{
			"doctype": ONBOARDING,
			"student": student,
			"template": template,
			"items": [{**item, "status": "Pending"} for item in items],
		}
	)
	try:
		return doc.insert(ignore_permissions=True).name
	except frappe.UniqueValidationError:  # unique on student: a concurrent creator won
		return frappe.db.get_value(ONBOARDING, {"student": student})


def mark_item_done(student, item_code):
	"""Tick `item_code` on the student's onboarding if it exists and is still Pending."""
	name = frappe.db.get_value(ONBOARDING, {"student": student})
	if not name:
		return
	doc = frappe.get_doc(
		ONBOARDING, name, for_update=True
	)  # locking read: the status check sees the latest row
	for row in doc.items:
		if row.item_code == item_code and row.status == "Pending":
			row.status = "Done"
			doc.save(ignore_permissions=True)
			return
