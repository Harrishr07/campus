"""M17-01 The OneBook Campus tile on the Apps screen (add_to_apps_screen in hooks)."""

import frappe
from frappe.desk.doctype.dock.dock import get_app_entry_set

from campus.campus_platform.pack_visibility import hidden_workspaces


def has_app_permission():
	"""Show the tile to a user who can open at least one campus area: a Dock entry the roles allow and no
	disabled module pack hides."""
	hidden = hidden_workspaces(frappe.session.user)
	return any(entry.get("link_to") not in hidden for entry in get_app_entry_set("campus"))
