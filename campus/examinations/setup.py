"""M12-02, M06-08 Examinations setup: the COE role used by the exam doctypes' permissions and the seed
approval policy of CIA Unlock Requests."""

import frappe

from campus.examinations.access import COE_ROLE

CIA_UNLOCK_POLICY = "CIA Unlock Approval"


def ensure_coe_role():
	if not frappe.db.exists("Role", COE_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": COE_ROLE, "desk_access": 1}).insert(ignore_permissions=True)


def seed_cia_unlock_policy():
	"""A single level, the COE of the request's company, unless the college has its own policy."""
	if frappe.db.exists("Approval Policy", {"document_type": "CIA Unlock Request"}) or not frappe.db.exists("Position", "COE"):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": CIA_UNLOCK_POLICY, "document_type": "CIA Unlock Request",
			"levels": [{"approver_type": "Position", "approver": "COE", "scope_field": "company", "title": "COE", "sla_hours": 24}],
		}
	).insert(ignore_permissions=True)  # fmt: skip
