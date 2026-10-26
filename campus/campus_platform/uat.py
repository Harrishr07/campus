"""PR-08 UAT support: the roles of the UAT Feedback DocType and the demo-site grant of the tester role.

UAT Tester files feedback (sees only their own rows); UAT Coordinator and System Manager triage all of it.
The kit gives every desk pilot user the tester role only where test passwords are allowed (a demo or developer-mode
site); a real site never gets it. Remove the DocType and both roles before go-live.
"""

import frappe

TESTER_ROLE = "UAT Tester"
COORDINATOR_ROLE = "UAT Coordinator"
SCRIPTS = (
	"accounts", "admission-officer", "coe", "faculty", "guardian", "hod", "iqac-coordinator",
	"mentor-class-advisor", "office-academics", "placement-officer", "principal", "student",
)  # fmt: skip


def ensure_uat_roles():
	"""Before the DocType syncs: its permissions name both roles."""
	for role in (TESTER_ROLE, COORDINATOR_ROLE):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def tester_roles_for(roles):
	"""The tester role for a pilot user with these roles, none for a portal-only user (it would give them the desk)."""
	ensure_uat_roles()
	if all(frappe.db.get_value("Role", role, "desk_access") == 0 for role in roles):
		return []
	return [TESTER_ROLE]
