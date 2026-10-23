"""M17-01 Frappe 16.53 converted the old campus sidebar fixtures into site-owned Sidebars on upgrade. Campus now
ships one standard Sidebar per area, which replaces the converted one of the same name; this removes the converted
ones the app does not ship (Campus Platform, which merged Approvals into Administration, and Campus Messaging), so
no module carries a stale second sidebar. Sidebars a site made itself carry no conversion record and stay."""

import frappe


def execute():
	modules = frappe.get_all("Module Def", {"app_name": "campus"}, pluck="name")
	for name in frappe.get_all(
		"Sidebar", {"module": ["in", modules], "standard": 0, "merged_from": ["is", "set"]}, pluck="name"
	):
		frappe.delete_doc("Sidebar", name, ignore_permissions=True, force=True)
