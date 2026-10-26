"""M02-03 Confidential bodies: meetings and action items of a body whose Body Type is Confidential (ICC,
Anti-Ragging, Grievance) are readable only by members of that body in office, the Principal and the System Manager.
Hooked as permission_query_conditions (lists) and has_permission (single documents)."""

import frappe
from frappe.utils import today

CONFIDENTIAL_SCOPED = ("Body Meeting", "Meeting Action Item")
OPEN_ROLES = ("Principal", "System Manager")


def hidden_bodies(user):
	"""Confidential bodies the user may not see: all of them except those the user sits on today."""
	if user == "Administrator" or set(OPEN_ROLES) & set(frappe.get_roles(user)):
		return []
	confidential = frappe.get_all("Body Type", {"confidential": 1}, pluck="name") or [""]
	bodies = frappe.get_all("Body", {"body_type": ["in", confidential]}, pluck="name")
	if not bodies:
		return []
	employees = frappe.get_all("Employee", {"user_id": user}, pluck="name") or [""]
	mine = set(
		frappe.db.sql_list(
			"""select parent from `tabBody Member` where parenttype = 'Body' and parent in %(bodies)s and employee in %(employees)s
			and from_date <= %(today)s and (to_date is null or to_date >= %(today)s)""",
			{"bodies": bodies, "employees": employees, "today": today()},
		)
	)
	return [b for b in bodies if b not in mine]


def permission_query(user=None, doctype="Body Meeting"):
	hidden = hidden_bodies(user or frappe.session.user)
	if not hidden:
		return ""
	return f"`tab{doctype}`.body not in ({', '.join(frappe.db.escape(b) for b in hidden)})"


def has_permission(doc, ptype=None, user=None):
	body = doc.get("body") or (
		doc.get("body_meeting") and frappe.db.get_value("Body Meeting", doc.body_meeting, "body")
	)
	return not body or body not in hidden_bodies(user or frappe.session.user)
