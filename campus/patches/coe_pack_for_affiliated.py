"""M06-10 The Examinations workspace (COE module pack) follows Examination Mode: an Affiliated college keeps CIA,
exam registration and the university exchange (its internal Result Run stays refused). Seeding never overwrites an
existing pack, so this adds the Affiliated status to the COE pack of an upgraded site."""

import frappe


def execute():
	if not frappe.db.exists("Module Pack", "COE"):
		return
	pack = frappe.get_doc("Module Pack", "COE")
	if any(row.status == "Affiliated" for row in pack.allowed_statuses):
		return
	pack.append("allowed_statuses", {"status": "Affiliated"})
	pack.save(ignore_permissions=True)  # Module Pack on_update clears the pack cache
