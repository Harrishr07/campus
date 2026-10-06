"""M09-04 No Dues sign-off rules: the standard offices, the roles that may clear each, and their seed data."""

import frappe
from frappe import _

STANDARD_OFFICES = ("Accounts", "Library", "Hostel", "Lab")
DEFAULT_OFFICE_ROLES = {
	"Accounts": ("Accounts User", "Accounts Manager"),
	"Library": ("Librarian",),
	"Hostel": ("Warden",),
	"Lab": ("Lab In-charge",),
}


def seed_office_roles():
	"""Create the missing office roles and, while Campus Settings maps no office yet, the default mapping."""
	for roles in DEFAULT_OFFICE_ROLES.values():
		for role in roles:
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
	settings = frappe.get_single("Campus Settings")
	if not settings.no_dues_office_roles:
		for office, roles in DEFAULT_OFFICE_ROLES.items():
			for role in roles:
				settings.append("no_dues_office_roles", {"office": office, "role": role})
		settings.save(ignore_permissions=True)


def clearing_roles(office):
	"""Roles allowed to clear `office` (case-insensitive); empty when the office has no mapping."""
	rows = frappe.get_single("Campus Settings").no_dues_office_roles
	return {row.role for row in rows if row.office.strip().lower() == office.strip().lower()}


def check_may_clear(office, user=None):
	roles = clearing_roles(office)
	if roles and not roles & set(frappe.get_roles(user)):
		frappe.throw(
			_("Only {0} can clear or reopen the {1} sign-off.").format(", ".join(sorted(roles)), office), frappe.PermissionError
		)
