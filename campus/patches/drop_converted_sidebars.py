"""M17-01 Frappe 16.53 converted the old campus sidebar fixtures into site-owned Sidebars on upgrade. Campus now
ships one standard Sidebar per area, so this removes every converted Sidebar in a campus module: a same-named one
is already replaced by the shipped one, and the others (Campus Platform, which merged Approvals into Administration,
and Campus Messaging) would leave a module with a stale second sidebar. Sidebars a site made itself carry no
conversion record and stay."""

import frappe


def execute():
	modules = frappe.get_all("Module Def", {"app_name": "campus"}, pluck="name")
	for name in frappe.get_all(
		"Sidebar", {"module": ["in", modules], "standard": 0, "merged_from": ["is", "set"]}, pluck="name"
	):
		frappe.delete_doc("Sidebar", name, ignore_permissions=True, force=True)
