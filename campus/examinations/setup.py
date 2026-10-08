"""M12-02, M06-08, M06-02 Examinations setup: the COE role used by the exam doctypes' permissions, the seed
approval policies of CIA Unlock Requests and Malpractice Reports, and the Exam Hall seat layout fields on Room."""

import frappe

from campus.examinations.access import COE_ROLE

CIA_UNLOCK_POLICY = "CIA Unlock Approval"
MALPRACTICE_POLICY = "Malpractice Approval"


def ensure_coe_role():
	if not frappe.db.exists("Role", COE_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": COE_ROLE, "desk_access": 1}).insert(ignore_permissions=True)


def setup_examinations():
	from campus.examinations.exam_halls import setup_exam_halls

	setup_exam_halls()
	seed_cia_unlock_policy()
	seed_coe_policy(MALPRACTICE_POLICY, "Malpractice Report")


def seed_cia_unlock_policy():
	seed_coe_policy(CIA_UNLOCK_POLICY, "CIA Unlock Request")


def seed_coe_policy(policy_name, document_type):
	"""A single level, the COE of the document's company, unless the college has its own policy."""
	if frappe.db.exists("Approval Policy", {"document_type": document_type}) or not frappe.db.exists("Position", "COE"):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": policy_name, "document_type": document_type,
			"levels": [{"approver_type": "Position", "approver": "COE", "scope_field": "company", "title": "COE", "sla_hours": 24}],
		}
	).insert(ignore_permissions=True)  # fmt: skip
