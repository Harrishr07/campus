"""M17-01 Keep Frappe's module map current during migrate.

Frappe builds `frappe.local.app_modules` at init from the cached `app_modules` key, which still lists the modules
of the previous modules.txt. Migrate clears that key and registers the new Module Def, but does not rebuild the
local map, so the doc sync walks the old module list and a module added since the last migrate (Campus Approvals)
is imported only by the next migrate. Rebuilding the map in `before_migrate`, which runs after the Module Defs are
synced and before the doc sync, makes the first migrate import it.
"""

import frappe


def refresh_module_map():
	"""Rebuild the module map when modules.txt lists a campus module it lacks; a no-op once current."""
	known = set((frappe.local.app_modules or {}).get("campus", []))
	if set(map(frappe.scrub, frappe.get_module_list("campus"))) - known:
		frappe.cache.delete_value("app_modules")
		frappe.client_cache.delete_value("installed_app_modules")
		frappe.setup_module_map()
