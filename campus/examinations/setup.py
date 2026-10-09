"""M12-02, M06-08, M06-02, M06-05 Examinations setup: the COE role used by the exam doctypes' permissions, the seed
approval policies of CIA Unlock Requests, Malpractice Reports and Mark Moderations, the result release notice
template, and the Exam Hall seat layout fields on Room."""

import frappe

from campus.examinations.access import COE_ROLE

CIA_UNLOCK_POLICY = "CIA Unlock Approval"
MALPRACTICE_POLICY = "Malpractice Approval"
MALPRACTICE_DECISION_FIELDS = "committee_decision\ndecision_remarks"  # the COE records the decision while approving
MODERATION_POLICY = "Mark Moderation Approval"


def ensure_coe_role():
	if not frappe.db.exists("Role", COE_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": COE_ROLE, "desk_access": 1}).insert(ignore_permissions=True)


def setup_examinations():
	from campus.examinations.exam_halls import setup_exam_halls
	from campus.examinations.publication import seed_release_template

	setup_exam_halls()
	seed_cia_unlock_policy()
	seed_coe_policy(MALPRACTICE_POLICY, "Malpractice Report", MALPRACTICE_DECISION_FIELDS)
	seed_coe_policy(MODERATION_POLICY, "Mark Moderation", position="PRINCIPAL", title="Principal")  # the COE proposes it
	seed_release_template()


def open_decision_to_approver():
	"""Sites seeded before the decision moved to the approver: let the seeded level edit it (a blank level only).
	Run once by the patch open_malpractice_decision_to_approver."""
	levels = frappe.get_all("Approval Level", {"parenttype": "Approval Policy", "parent": MALPRACTICE_POLICY}, ["name", "can_edit_fields"])
	for level in levels:
		if not level.can_edit_fields:
			frappe.db.set_value("Approval Level", level.name, "can_edit_fields", MALPRACTICE_DECISION_FIELDS)


def seed_cia_unlock_policy():
	seed_coe_policy(CIA_UNLOCK_POLICY, "CIA Unlock Request")


def seed_coe_policy(policy_name, document_type, can_edit_fields=None, position="COE", title="COE"):
	"""A single level, the `position` holder (default the COE) of the document's company, unless the college has its
	own policy."""
	if frappe.db.exists("Approval Policy", {"document_type": document_type}) or not frappe.db.exists("Position", position):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": policy_name, "document_type": document_type,
			"levels": [
				{"approver_type": "Position", "approver": position, "scope_field": "company", "title": title, "sla_hours": 24,
				"can_edit_fields": can_edit_fields}
			],
		}
	).insert(ignore_permissions=True)  # fmt: skip
