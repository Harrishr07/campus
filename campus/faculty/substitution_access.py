"""M07-03 Who sees Substitutions: department staff roles see all; a teacher holding none of them (the Instructor role
alone) sees only the substitutions that name them as the substitute, read-only."""

import frappe

STAFF_ROLES = ("System Manager", "Academics User", "HOD", "Dean Academics", "Principal", "HR Manager")
READ_TYPES = ("read", "print", "email", "export", "report", "select")


def sees_only_own(user):
	return user != "Administrator" and not set(STAFF_ROLES) & set(frappe.get_roles(user))


def permission_query(user=None):
	user = user or frappe.session.user
	if not sees_only_own(user):
		return ""
	return f"`tabSubstitution`.substitute_user = {frappe.db.escape(user)}"


def has_permission(doc, ptype=None, user=None):
	"""Deny-only hook (a controller hook cannot grant): the Instructor role alone reads its own substitutions."""
	user = user or frappe.session.user
	if not sees_only_own(user):
		return True
	return ptype in READ_TYPES and doc.get("substitute_user") == user
