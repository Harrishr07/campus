"""M09 Campus Finance setup: custom fields on Fee Category, Fee Structure, Sales Invoice and Payment Entry, and the seed fee heads."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from campus.campus_finance.fee_heads import FEE_HEADS, seed_fee_categories
from campus.campus_finance.no_dues import seed_office_roles

MODULE = "Campus Finance"


def field(fieldname, fieldtype, label, insert_after, **kwargs):
	return {
		"fieldname": fieldname, "fieldtype": fieldtype, "label": label, "insert_after": insert_after,
		"module": MODULE, **kwargs,
	}  # fmt: skip


CONCESSION_POLICY = "Fee Concession Approval"


def setup_finance():
	setup_finance_fields()
	seed_fee_categories()
	seed_office_roles()
	seed_concession_policy()


def seed_concession_policy():
	"""A single Principal level for Fee Concessions, unless the college has its own policy for them."""
	if frappe.db.exists("Approval Policy", {"document_type": "Fee Concession"}) or not frappe.db.exists("Position", "PRINCIPAL"):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": CONCESSION_POLICY, "document_type": "Fee Concession",
			"levels": [{"approver_type": "Position", "approver": "PRINCIPAL", "scope_field": "company", "title": "Principal", "sla_hours": 72}],
		}
	).insert(ignore_permissions=True)


def setup_finance_fields():
	"""Create/refresh the finance custom fields. Idempotent."""
	head_types = "\n".join(FEE_HEADS) + "\nOther"
	create_custom_fields(
		{
			"Fee Category": [
				field("oc_fee_head_type", "Select", "Fee Head Type", "category_name", options=head_types,
					in_list_view=1, in_standard_filter=1),
				field("oc_refundable", "Check", "Refundable", "oc_fee_head_type"),
				field("oc_gst_applicable", "Check", "GST Applicable", "oc_refundable"),
				field("oc_concession_allowed", "Check", "Concession Allowed", "oc_gst_applicable",
					description="Fee Concessions may discount this category."),
			],
			"Fee Structure": [
				field("oc_admission_quota", "Link", "Admission Quota", "student_category", options="Admission Quota",
					in_standard_filter=1),
			],
			"Sales Invoice": [
				field("oc_challan_no", "Data", "Challan No", "fee_schedule", unique=1, read_only=1, no_copy=1,
					search_index=1, description="Bank challan number; used to match bank collections."),
			],
			"Sales Invoice Item": [
				field("oc_fee_concession", "Link", "Fee Concession", "description", options="Fee Concession", read_only=1,
					no_copy=1, description="Set on the discount line a Fee Concession adds."),
			],
			"Payment Entry": [
				field("oc_student", "Link", "Student", "party_name", options="Student", read_only=1, no_copy=1,
					search_index=1),
				field("oc_receipt_no", "Data", "Fee Receipt No", "oc_student", unique=1, read_only=1, no_copy=1),
			],
		},
		update=True,
	)
