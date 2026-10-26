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


MANAGER_ROLES = {"System Manager", "Accounts Manager"}


def seed_office_roles():
	"""Create the missing office roles and the default mapping of every standard office that has none."""
	for roles in DEFAULT_OFFICE_ROLES.values():
		for role in roles:
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
					ignore_permissions=True
				)
	settings = frappe.get_single("Campus Settings")
	changed = False
	for office, roles in DEFAULT_OFFICE_ROLES.items():
		if not clearing_roles(office):
			changed = True
			for role in roles:
				settings.append("no_dues_office_roles", {"office": office, "role": role})
	if changed:
		settings.save(ignore_permissions=True)


def normalise(office):
	return " ".join((office or "").split()).lower()


def clearing_roles(office):
	"""Roles allowed to clear `office` (case and spacing ignored); empty when the office has no mapping."""
	rows = frappe.get_single("Campus Settings").no_dues_office_roles
	return {row.role for row in rows if normalise(row.office) == normalise(office)}


def may_clear(office, user=None):
	"""Whether the user may clear or reopen `office`. An office with no mapping is for managers only (fail closed)."""
	roles = clearing_roles(office) or MANAGER_ROLES
	return bool(roles & set(frappe.get_roles(user)))


def check_may_clear(office, user=None):
	if not may_clear(office, user):
		roles = clearing_roles(office) or MANAGER_ROLES
		frappe.throw(
			_("Only {0} can clear or reopen the {1} sign-off.").format(", ".join(sorted(roles)), office),
			frappe.PermissionError,
		)
