"""M12-02 Role used by the examination doctypes' permissions."""

import frappe

from campus.examinations.access import COE_ROLE


def ensure_coe_role():
	if not frappe.db.exists("Role", COE_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": COE_ROLE, "desk_access": 1}).insert(ignore_permissions=True)
