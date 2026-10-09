"""M12-02, M06-08, M06-02 Examinations setup: the COE role used by the exam doctypes' permissions, the seed
approval policies of CIA Unlock Requests and Malpractice Reports, and the Exam Hall seat layout fields on Room."""

import frappe

from campus.examinations.access import COE_ROLE

CIA_UNLOCK_POLICY = "CIA Unlock Approval"
MALPRACTICE_POLICY = "Malpractice Approval"
MALPRACTICE_DECISION_FIELDS = "committee_decision\ndecision_remarks"  # the COE records the decision while approving


def ensure_coe_role():
	if not frappe.db.exists("Role", COE_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": COE_ROLE, "desk_access": 1}).insert(ignore_permissions=True)


def setup_examinations():
	from campus.examinations.exam_halls import setup_exam_halls

	setup_exam_halls()
	seed_cia_unlock_policy()
	seed_coe_policy(MALPRACTICE_POLICY, "Malpractice Report", MALPRACTICE_DECISION_FIELDS)


def open_decision_to_approver():
	"""Sites seeded before the decision moved to the approver: let the seeded level edit it (a blank level only).
	Run once by the patch open_malpractice_decision_to_approver."""
	levels = frappe.get_all("Approval Level", {"parenttype": "Approval Policy", "parent": MALPRACTICE_POLICY}, ["name", "can_edit_fields"])
	for level in levels:
		if not level.can_edit_fields:
			frappe.db.set_value("Approval Level", level.name, "can_edit_fields", MALPRACTICE_DECISION_FIELDS)


def seed_cia_unlock_policy():
	seed_coe_policy(CIA_UNLOCK_POLICY, "CIA Unlock Request")


def seed_coe_policy(policy_name, document_type, can_edit_fields=None):
	"""A single level, the COE of the document's company, unless the college has its own policy."""
	if frappe.db.exists("Approval Policy", {"document_type": document_type}) or not frappe.db.exists("Position", "COE"):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": policy_name, "document_type": document_type,
			"levels": [
				{"approver_type": "Position", "approver": "COE", "scope_field": "company", "title": "COE", "sla_hours": 24,
				"can_edit_fields": can_edit_fields}
			],
		}
	).insert(ignore_permissions=True)  # fmt: skip
