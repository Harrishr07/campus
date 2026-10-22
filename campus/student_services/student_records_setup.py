"""M06-01, M05-03 Student records setup (after_install / after_migrate, via setup_student_services).

The withdrawal window and the break of study limits are regulation values, so they live on the regulation's
Exam Rule Set. They are Custom Fields made here (not JSON fields) so the Exam Rule Set DocType stays with the
examinations module; a new column takes its default on existing records. The HOD -> Principal approval
policies of the Exam Withdrawal Application, Break of Study and Rejoin Application are seeded unless the college
has its own.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Student Services"
RECORD_DOCTYPES = ("Exam Withdrawal Application", "Break of Study", "Rejoin Application")
# title, position, scope field, SLA hours
LEVELS = [("HOD recommendation", "HOD", "department", 48), ("Principal approval", "PRINCIPAL", "company", 72)]


def setup_student_records():
	create_custom_fields({"Exam Rule Set": exam_rule_set_fields()}, update=True)
	seed_policies()
	seed_correction_policies()


def seed_correction_policies():
	from campus.student_services import corrections  # L-08 (lazy: corrections imports admissions)

	corrections.seed_policies()


def exam_rule_set_fields():
	return [
		{"fieldname": "oc_student_records_section", "fieldtype": "Section Break", "label": "Withdrawal and Break of Study",
			"insert_after": "internal_only_min_pct", "module": MODULE},
		{"fieldname": "oc_withdrawal_days", "fieldtype": "Int", "label": "Withdrawal Window (days after the exam)",
			"insert_after": "oc_student_records_section", "default": "10", "non_negative": 1, "module": MODULE,
			"description": "An Exam Withdrawal Application later than this needs the Principal's special case."},
		{"fieldname": "oc_student_records_column", "fieldtype": "Column Break", "insert_after": "oc_withdrawal_days",
			"module": MODULE},
		{"fieldname": "oc_break_max_years", "fieldtype": "Int", "label": "Break of Study Maximum (years)",
			"insert_after": "oc_student_records_column", "default": "1", "non_negative": 1, "module": MODULE},
		{"fieldname": "oc_break_exceptional_years", "fieldtype": "Int", "label": "Exceptional Extra Break (years)",
			"insert_after": "oc_break_max_years", "default": "1", "non_negative": 1, "module": MODULE,
			"description": "Allowed on top of the maximum for a break marked exceptional."},
	]  # fmt: skip


def seed_policies():
	if not (frappe.db.exists("Position", "HOD") and frappe.db.exists("Position", "PRINCIPAL")):
		return
	for doctype in RECORD_DOCTYPES:
		if frappe.db.exists("Approval Policy", {"document_type": doctype}):
			continue
		frappe.get_doc(
			{
				"doctype": "Approval Policy", "policy_name": doctype, "document_type": doctype,
				"levels": [
					{"title": title, "approver_type": "Position", "approver": position, "scope_field": scope, "sla_hours": hours}
					for title, position, scope, hours in LEVELS
				],
			}
		).insert(ignore_permissions=True)  # fmt: skip
