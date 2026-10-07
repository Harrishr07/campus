"""M05-01, M05-02 Student Services setup: Student profile fields, leave kind and certificate on Student Leave Application
(with their submit check), certificate types, default onboarding templates, Mentor read right."""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.permissions import add_permission

from campus.examinations.access import MENTOR_ROLE
from campus.student_services.attendance_rules import MEDICAL, ON_DUTY
from campus.student_services.onboarding import ensure_default_templates

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
	"""Create/refresh the Student and Student Leave Application custom fields, the Mentor read right and the seed
	records (certificate types, default onboarding templates). Idempotent."""
	setup_student_fields()
	ensure_mentor_read_access()
	seed_certificate_types()
	ensure_default_templates()
	setup_leave_fields()


def field(fieldname, fieldtype, label, insert_after, **kwargs):
	return {
		"fieldname": fieldname, "fieldtype": fieldtype, "label": label,
		"insert_after": insert_after, "module": MODULE, **kwargs,
	}  # fmt: skip


def student_fields():
	"""The blueprint section 7 Student fields not defined elsewhere (company, register/roll no, regulation, batch live
	with their own modules)."""
	return [
		field("oc_profile_section", "Section Break", "Campus Profile", "oc_regulation_history"),
		field("oc_admission_quota", "Link", "Admission Quota", "oc_profile_section", options="Admission Quota",
			in_standard_filter=1),
		field("oc_current_semester", "Int", "Current Semester", "oc_admission_quota", in_standard_filter=1),
		field("oc_section", "Data", "Section", "oc_current_semester"),
		field("oc_academic_status", "Select", "Academic Status", "oc_section",
			options="\n".join(ACADEMIC_STATUSES), default="Active", in_standard_filter=1),
		field("oc_abc_id", "Data", "ABC ID", "oc_academic_status", description="Academic Bank of Credits id."),
		field("oc_profile_column", "Column Break", None, "oc_abc_id"),
		field("oc_mentor", "Link", "Mentor", "oc_profile_column", options="Employee", in_standard_filter=1,
			description="Set by the mentor allocation tool."),
		field("oc_class_advisor", "Link", "Class Advisor", "oc_mentor", options="User", read_only=1, no_copy=1,
			description="Resolved from the CLASS-ADVISOR Position Holder of the student's group when saved."),
		field("oc_hostel_resident", "Check", "Hostel Resident", "oc_class_advisor"),
		field("oc_transport_user", "Check", "Transport User", "oc_hostel_resident"),
		field("oc_first_graduate", "Check", "First Graduate", "oc_transport_user"),
		field("oc_differently_abled", "Check", "Differently Abled", "oc_first_graduate"),
		field("oc_lateral_entry", "Check", "Lateral Entry", "oc_differently_abled"),
		field("oc_onboarding_completion", "Percent", "Onboarding Completion", "oc_lateral_entry", read_only=1,
			no_copy=1, description="From the Student Onboarding."),
	]  # fmt: skip


def setup_student_fields():
	create_custom_fields({"Student": student_fields()}, update=True)


def ensure_mentor_read_access():
	"""The Mentor role (granted by holding the MENTOR position) reads Student; campus.examinations.access narrows
	that to the user's own mentees."""
	if not frappe.db.exists("Role", MENTOR_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": MENTOR_ROLE, "desk_access": 1}).insert(ignore_permissions=True)
	if not frappe.db.exists("Custom DocPerm", {"parent": "Student", "role": MENTOR_ROLE, "permlevel": 0}):
		add_permission("Student", MENTOR_ROLE, 0)


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
