"""M16 Company of a message: derived from the record it is about, else from the recipient.

Message Logs and consents carry `company` so reports can be filtered by it and by User Permissions.
Students and employees carry their own company; a guardian takes the company of their first student.
"""

import frappe

COMPANY_FIELDS = ("oc_company", "company")


def company_of(doctype, name):
	"""Company of a record, or None when its doctype has no company field (or the record is missing)."""
	if not doctype or not name:
		return None
	if doctype == "Guardian":
		student = frappe.db.get_value("Student Guardian", {"guardian": name, "parenttype": "Student"}, "parent")
		return student and company_of("Student", student)
	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		return None
	fieldname = next((f for f in COMPANY_FIELDS if meta.has_field(f)), None)
	return fieldname and frappe.db.get_value(doctype, name, fieldname)
