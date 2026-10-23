"""M17-01 Students and guardians use the campus portal, never the desk: their roles carry no desk access."""

import frappe

PORTAL_ONLY_ROLES = ("Student", "Guardian")


def restrict_portal_roles():
	"""Idempotent: the education app creates Student and Guardian with desk access; take it away."""
	for role in PORTAL_ONLY_ROLES:
		if frappe.db.get_value("Role", role, "desk_access"):
			frappe.db.set_value("Role", role, "desk_access", 0)
