"""M04-01 Admissions module setup: Student Applicant and Student custom fields, the Aadhaar Viewer role."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from campus.admissions.aadhaar import VIEWER_ROLE

MODULE = "Admissions"
ADMISSION_TYPES = ("Regular", "Lateral", "PG", "Transfer")
OVERRIDE_ROLE = "Admission Override"  # may admit into a full quota/category row (logged)
VERIFIER_ROLE = "Admission Verifier"  # may mark applicant documents Verified or Rejected
OFFICER_ROLE = "Admission Officer"  # may admit approved applicants and cancel admissions


def setup_admissions():
	ensure_aadhaar_role()
	ensure_admission_roles()
	setup_admission_fields()


def ensure_admission_roles():
	for role in (OVERRIDE_ROLE, VERIFIER_ROLE, OFFICER_ROLE):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def ensure_aadhaar_role():
	if not frappe.db.exists("Role", VIEWER_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": VIEWER_ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)


def field(fieldname, fieldtype, label, insert_after, **kwargs):
	return {
		"fieldname": fieldname, "fieldtype": fieldtype, "label": label,
		"insert_after": insert_after, "module": MODULE, **kwargs,
	}  # fmt: skip


def aadhaar_fields(insert_after):
	"""Entry field (encrypted, never printed or copied) plus the read-only masked display."""
	return [
		field("oc_aadhaar_section", "Section Break", "Aadhaar", insert_after),
		field(
			"oc_aadhaar", "Password", "Aadhaar Number", "oc_aadhaar_section",
			print_hide=1, report_hide=1, no_copy=1, permlevel=0,
			description="Stored encrypted. Only the masked number is shown.",
		),
		field(
			"oc_aadhaar_masked", "Data", "Aadhaar (Masked)", "oc_aadhaar",
			read_only=1, no_copy=1, in_list_view=0,
		),
	]  # fmt: skip


def setup_admission_fields():
	"""Create/refresh the admission fields. Idempotent."""
	applicant = [
		field("oc_admission_section", "Section Break", "Admission", "student_category"),
		field("oc_admission_type", "Select", "Admission Type", "oc_admission_section",
			options="\n" + "\n".join(ADMISSION_TYPES), in_standard_filter=1),
		field("oc_admission_quota", "Link", "Admission Quota", "oc_admission_type",
			options="Admission Quota", in_standard_filter=1),
		field("oc_counselling_authority", "Link", "Counselling Authority", "oc_admission_quota",
			options="Counselling Authority"),
		field("oc_lead", "Link", "Enquiry (Lead)", "oc_counselling_authority", options="Lead"),
		field("oc_admission_column", "Column Break", None, "oc_lead"),
		field("oc_allotment_no", "Data", "Allotment No", "oc_admission_column", search_index=1),
		field("oc_allotment_key", "Data", "Allotment Key", "oc_allotment_no", unique=1, hidden=1, read_only=1,
			no_copy=1, description="Counselling authority and allotment number: one applicant per allotment."),
		field("oc_allotment_date", "Date", "Allotment Date", "oc_allotment_key"),
		field("oc_rank", "Int", "Rank", "oc_allotment_date"),
		field("oc_cutoff", "Float", "Cutoff", "oc_rank"),
		field("oc_first_graduate", "Check", "First Graduate", "oc_cutoff"),
		field("oc_differently_abled", "Check", "Differently Abled", "oc_first_graduate"),
		field("oc_marks_section", "Section Break", "Qualifying Marks", "oc_differently_abled"),
		field("oc_qualifying_marks", "Table", "Qualifying Marks", "oc_marks_section",
			options="Applicant Qualifying Mark"),
		field("oc_eligibility_status", "Select", "Eligibility", "oc_qualifying_marks",
			options="Pending\nEligible\nIneligible", default="Pending", read_only=1, no_copy=1,
			in_standard_filter=1),
		field("oc_eligibility_reasons", "Small Text", "Eligibility Reasons", "oc_eligibility_status",
			read_only=1, no_copy=1),
		field("oc_documents_section", "Section Break", "Documents", "oc_eligibility_reasons"),
		field("oc_documents", "Table", "Documents", "oc_documents_section", options="Applicant Document"),
		*aadhaar_fields("oc_documents"),
	]  # fmt: skip
	student = aadhaar_fields("student_email_id")
	enrollment = [
		field("oc_admission_quota", "Link", "Admission Quota", "student_category", options="Admission Quota",
			in_standard_filter=1, description="Counted against the Seat Matrix when submitted."),
	]  # fmt: skip
	student += [
		field("oc_register_no", "Data", "Register No", "student_applicant", unique=1, read_only=1, no_copy=1,
			in_standard_filter=1, description="Assigned at admission from the Admission Settings pattern."),
		field("oc_roll_no", "Data", "Roll No", "oc_register_no", read_only=1, no_copy=1),
	]  # fmt: skip
	invoice = [
		field("oc_program_enrollment", "Link", "Admission Enrollment", "student", options="Program Enrollment",
			read_only=1, no_copy=1, search_index=1, description="Set on the fee invoice raised at admission."),
	]  # fmt: skip
	create_custom_fields(
		{"Student Applicant": applicant, "Student": student, "Program Enrollment": enrollment, "Sales Invoice": invoice},
		update=True,
	)
