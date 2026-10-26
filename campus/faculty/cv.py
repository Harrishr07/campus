"""M07-04 Faculty CV data for the Employee print format (a Jinja method, hooks.py): verified achievements and the FDPs attended, read with the
printing user's permissions. The print format escapes everything it shows."""

import frappe


def faculty_cv_sections(employee):
	"""{"achievements": [...], "fdps": [...]} of `employee`, newest first."""
	frappe.has_permission("Employee", "read", employee, throw=True)
	achievements = frappe.get_list(
		"Faculty Achievement",
		{"employee": employee, "verified": 1},
		["achievement_type", "title", "achievement_date"],
		order_by="achievement_date desc, name", limit_page_length=0,
	)  # fmt: skip
	events = frappe.get_all(
		"Training Event Employee",
		{"employee": employee, "attendance": "Present", "parenttype": "Training Event"},
		pluck="parent",
	)
	fdps = frappe.get_all(  # after the Employee read check above: a teacher sees their own FDPs without Training Event rights
		"Training Event",
		{"name": ["in", events or [""]], "oc_is_fdp": 1, "docstatus": 1},
		["event_name", "start_time"],
		order_by="start_time desc", limit_page_length=0,
	)  # fmt: skip
	return {"achievements": achievements, "fdps": fdps}
