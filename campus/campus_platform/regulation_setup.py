"""M02-04 Student custom fields and the Dean Academics role for regulation management."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Campus Platform"
DEAN_ROLE = "Dean Academics"


def setup_regulation_fields():
	"""Create/refresh the regulation fields on Student. Idempotent; run on install and migrate."""
	fields = [
		{
			"fieldname": "oc_regulation_section",
			"label": "Regulation",
			"fieldtype": "Section Break",
			"insert_after": "oc_company",
			"module": MODULE,
		},
		{
			"fieldname": "oc_batch",
			"label": "Batch (Admission Year)",
			"fieldtype": "Link",
			"options": "Academic Year",
			"insert_after": "oc_regulation_section",
			"in_standard_filter": 1,
			"module": MODULE,
		},
		{
			"fieldname": "oc_regulation",
			"label": "Regulation",
			"fieldtype": "Link",
			"options": "Regulation",
			"insert_after": "oc_batch",
			"in_standard_filter": 1,
			"read_only_depends_on": "eval:doc.oc_regulation",
			"description": "Assigned at Program Enrollment. Changed only by the Dean Academics.",
			"module": MODULE,
		},
		{
			"fieldname": "oc_regulation_history",
			"label": "Regulation History",
			"fieldtype": "Table",
			"options": "Regulation History",
			"insert_after": "oc_regulation",
			"read_only": 1,
			"module": MODULE,
		},
	]
	create_custom_fields({"Student": fields}, update=True)


def ensure_dean_role():
	if not frappe.db.exists("Role", DEAN_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": DEAN_ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)
