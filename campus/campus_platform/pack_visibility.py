"""M17-01 Hide the workspaces of disabled module packs from desk navigation.

Mechanism: the `boot_session` hook removes a pack's workspaces (pages, sidebar items, desktop icons)
from a user's boot data when the pack is disabled for ALL companies the user can access, or when the
pack lists roles and the user has none of them. System Manager and Administrator always see everything.
This hides navigation only; data access stays governed by DocType permissions.
"""

import frappe
from frappe.core.doctype.user_permission.user_permission import get_user_permissions

from campus.campus_platform.api import pack_enabled


def accessible_companies(user):
	restricted = [p["doc"] for p in get_user_permissions(user).get("Company", [])]
	return restricted or frappe.get_all("Institution Profile", pluck="name")


def hidden_workspaces(user):
	"""Names of workspaces that belong to a pack the user may not see."""
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return set()
	user_roles = set(frappe.get_roles(user))
	companies = accessible_companies(user)
	hidden = set()
	for pack in frappe.get_all("Module Pack", pluck="name"):
		workspaces = frappe.get_all("Module Pack Workspace", filters={"parent": pack}, pluck="workspace")
		if not workspaces:
			continue
		roles = set(frappe.get_all("Module Pack Role", filters={"parent": pack}, pluck="role"))
		if (roles and not roles & user_roles) or not any(pack_enabled(c, pack) for c in companies):
			hidden.update(workspaces)
	return hidden


def boot_session(bootinfo):
	hidden = hidden_workspaces(frappe.session.user)
	if hidden:
		filter_bootinfo(bootinfo, hidden)


def filter_bootinfo(bootinfo, hidden):
	workspaces = bootinfo.get("workspaces") or {}
	for key in ("pages", "private_pages"):
		if key in workspaces:
			workspaces[key] = [p for p in workspaces[key] if p.get("name") not in hidden]

	sidebars = bootinfo.get("workspace_sidebar_item") or {}
	for title, sidebar in list(sidebars.items()):
		if sidebar.get("label") in hidden:  # the sidebar of a hidden workspace goes with it
			del sidebars[title]
			continue
		sidebar["items"] = [
			i for i in sidebar["items"] if not (i.get("link_type") == "Workspace" and i.get("link_to") in hidden)
		]
		if not any(i.get("type") != "Section Break" for i in sidebar["items"]):
			del sidebars[title]

	bootinfo["desktop_icons"] = [
		i
		for i in bootinfo.get("desktop_icons") or []
		if not (i.get("link_type") == "Workspace" and i.get("link_to") in hidden)
		and not (i.get("link_type") == "Workspace Sidebar" and i.get("label", "").lower() not in sidebars)
	]
