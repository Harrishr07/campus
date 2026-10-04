"""M17-01 Seed Module Pack records (idempotent: existing packs are never overwritten)."""

import frappe

ALL_STATUSES = ["Affiliated", "Autonomous", "Deemed"]
AUTONOMOUS_ONLY = ["Autonomous", "Deemed"]

SEED_PACKS = {
	"COE": ("Controller of Examinations", AUTONOMOUS_ONLY),
	"GOVERNANCE": ("Academic Governance", AUTONOMOUS_ONLY),
	"HOSTEL": ("Hostel", ALL_STATUSES),
	"TRANSPORT": ("Transport", ALL_STATUSES),
	"LABS": ("Labs", ALL_STATUSES),
	"CLINICAL": ("Clinical", ALL_STATUSES),
	"PLACEMENT": ("Placement", ALL_STATUSES),
	"ALUMNI": ("Alumni", ALL_STATUSES),
	"LIBRARY": ("Library", ALL_STATUSES),
	"RESEARCH": ("Research", ALL_STATUSES),
	"IQAC": ("IQAC", ALL_STATUSES),
}


def seed_module_packs():
	for code, (title, statuses) in SEED_PACKS.items():
		if frappe.db.exists("Module Pack", code):
			continue
		frappe.get_doc(
			{
				"doctype": "Module Pack",
				"code": code,
				"title": title,
				"allowed_statuses": [{"status": s} for s in statuses],
			}
		).insert(ignore_permissions=True)
