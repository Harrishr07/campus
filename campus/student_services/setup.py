"""M05-02 Student Services setup: leave kind and certificate on Student Leave Application, with their submit check."""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from campus.student_services.attendance_rules import MEDICAL, ON_DUTY

MODULE = "Student Services"
LEAVE_KINDS = ["Leave", MEDICAL, ON_DUTY]
EVIDENCE_KINDS = (MEDICAL, ON_DUTY)


ACADEMIC_STATUSES = ["Active", "Detained", "Discontinued", "Completed", "Long Absent"]

# name, print format, number prefix, needs approval, transfer certificate
CERTIFICATE_TYPES = [
	("Bonafide", "Bonafide Certificate", "BON/{abbr}/{yyyy}/", 1, 0),
	("Conduct", "Conduct Certificate", "CON/{abbr}/{yyyy}/", 1, 0),
	("Course Completion", "Course Completion Certificate", "CCC/{abbr}/{yyyy}/", 1, 0),
	("Migration", "Migration Certificate", "MIG/{abbr}/{yyyy}/", 1, 0),
	("Medium of Instruction", "Medium of Instruction Certificate", "MOI/{abbr}/{yyyy}/", 1, 0),
	("Transfer Certificate", "Transfer Certificate", "TC/{abbr}/{yyyy}/", 1, 1),
]  # fmt: skip


def setup_student_services():
	"""Create/refresh the Student and Student Leave Application custom fields and the seed certificate types. Idempotent."""
	setup_student_fields()
	seed_certificate_types()
	setup_leave_fields()


def setup_student_fields():
	create_custom_fields(
		{
			"Student": [
				{
					"fieldname": "oc_academic_status", "fieldtype": "Select", "label": "Academic Status",
					"options": "\n".join(ACADEMIC_STATUSES), "default": "Active", "insert_after": "oc_section",
					"in_standard_filter": 1, "module": MODULE,
				},
			]
		},
		update=True,
	)


def seed_certificate_types():
	"""The standard certificate types. Existing ones are left as the college configured them (fee, approval...)."""
	for name, print_format, prefix, needs_approval, transfer in CERTIFICATE_TYPES:
		if not frappe.db.exists("Certificate Type", name) and frappe.db.exists("Print Format", print_format):
			frappe.get_doc(
				{
					"doctype": "Certificate Type", "type_name": name, "print_format": print_format, "number_prefix": prefix,
					"needs_approval": needs_approval, "verifiable": 1, "is_transfer_certificate": transfer, "enabled": 1,
				}
			).insert(ignore_permissions=True)


def setup_leave_fields():
	"""Create/refresh the Student Leave Application custom fields."""
	create_custom_fields(
		{
			"Student Leave Application": [
				{
					"fieldname": "oc_leave_kind", "fieldtype": "Select", "label": "Leave Kind",
					"options": "\n".join(LEAVE_KINDS), "default": "Leave", "insert_after": "to_date", "reqd": 1,
					"in_list_view": 1, "in_standard_filter": 1, "module": MODULE,
					"description": "Medical and On Duty leave count towards attendance as the Attendance Rule says.",
				},
				{
					"fieldname": "oc_certificate", "fieldtype": "Attach", "label": "Certificate",
					"insert_after": "oc_leave_kind", "module": MODULE,
					"depends_on": "eval:doc.oc_leave_kind != 'Leave'",
					"description": "Medical certificate or On Duty permission letter.",
				},
			]
		},
		update=True,
	)


def require_certificate(doc, method=None):
	"""Doc event (Student Leave Application before_submit): Medical and On Duty leave need their certificate."""
	if doc.oc_leave_kind in EVIDENCE_KINDS and not doc.oc_certificate:
		frappe.throw(_("Attach the certificate for {0} leave before submitting.").format(_(doc.oc_leave_kind)))
