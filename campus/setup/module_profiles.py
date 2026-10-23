"""PR-02 Pilot module profiles: each pilot desk user sees the campus areas plus only the non-campus modules its work needs.

Frappe's Dock lists every installed app's modules, and a Dock row of type Sidebar is hidden for a user only through the
user's blocked modules. A Module Profile is the standard way to set them, so the kit defines one per pilot role group
(the profile's `module_profiles`) and gives each desk user its `module_profile`.

A profile names the modules to KEEP; what it blocks is every module of an app other than campus that is not kept, worked
out from the site's Module Defs on each run, so an app installed later is blocked too. Core, Desk and Custom are never
blocked: they hold no navigation, only system pages. Re-running changes nothing; a user outside the kit is never touched.
"""

import frappe
from frappe import _

from campus.setup.people import user_email

APP = "campus"
NEVER_BLOCKED = {"Core", "Desk", "Custom"}


def ensure_module_profiles(profile, out):
	"""Create or update the profile's Module Profiles and give them to the kit users that name one."""
	blockable = blockable_modules()
	for spec in profile.get("module_profiles", []):
		ensure_module_profile(spec, blocked_for(spec, blockable), out)
	for user in profile.get("users", []):
		if user.get("module_profile"):
			assign_module_profile(user_email(profile, user["key"]), user["module_profile"], out)


def blockable_modules():
	"""Every module of a non-campus app, plus custom modules, that a profile may block."""
	modules = frappe.get_all("Module Def", filters={"app_name": ["!=", APP]}, pluck="name")
	modules += frappe.get_all("Module Def", filters={"custom": 1}, pluck="name")
	return sorted(set(modules) - NEVER_BLOCKED - campus_modules())


def campus_modules():
	return set(frappe.get_all("Module Def", filters={"app_name": APP}, pluck="name"))


def blocked_for(spec, blockable):
	return [module for module in blockable if module not in spec.get("keep", [])]


def ensure_module_profile(spec, blocked, out):
	name = spec["name"]
	if not frappe.db.exists("Module Profile", name):
		doc = frappe.get_doc({"doctype": "Module Profile", "module_profile_name": name})
		doc.set("block_modules", [{"module": module} for module in blocked])
		doc.insert(ignore_permissions=True)
		out.created["Module Profile"] += 1
		return
	doc = frappe.get_doc("Module Profile", name)
	if {row.module for row in doc.block_modules} == set(blocked):
		return
	doc.set("block_modules", [{"module": module} for module in blocked])
	doc.save(ignore_permissions=True)  # Frappe pushes the new blocked modules to every user of the profile
	out.updated["Module Profile"] += 1


def assign_module_profile(user, module_profile, out):
	"""Give `user` the profile (Frappe's User.validate copies its blocked modules); a user already on it is left alone."""
	if frappe.db.get_value("User", user, "module_profile") == module_profile:
		return
	doc = frappe.get_doc("User", user)
	doc.module_profile = module_profile
	doc.save(ignore_permissions=True)
	out.updated["User"] += 1
