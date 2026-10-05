"""M04-01 Admissions module setup: Student Applicant and Student custom fields, the Aadhaar Viewer role."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from campus.admissions.aadhaar import VIEWER_ROLE

MODULE = "Admissions"
ADMISSION_TYPES = ("Regular", "Lateral", "PG", "Transfer")


def setup_admissions():
	ensure_aadhaar_role()
	setup_admission_fields()


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
		field("oc_allotment_date", "Date", "Allotment Date", "oc_allotment_no"),
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
	create_custom_fields({"Student Applicant": applicant, "Student": student}, update=True)
