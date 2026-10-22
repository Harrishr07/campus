"""M05-12 / M04-09 follow-up (L-07 review I-3): only the joining confirmation sets a Program Enrollment's attendance
start date, which narrows the attendance denominator.

The first joining_gate patch filled it with the enrollment date on every enrollment that existed then, so a legacy
enrollment dated mid-term stopped counting the sessions before that date. Those enrollments are the ones created
before joining_gate ran (its Patch Log time; oc_joining_key cannot tell them apart, as the patch keyed them too): their
start date is cleared, so the whole term counts again. Enrollments made by a joining confirmation came later and keep
theirs. Idempotent.
"""

import frappe


def execute():
	gate_ran = frappe.db.get_value("Patch Log", {"patch": "campus.patches.joining_gate"}, "creation")
	if not gate_ran or not frappe.db.has_column("Program Enrollment", "oc_attendance_start_date"):
		return
	frappe.db.sql(
		"update `tabProgram Enrollment` set oc_attendance_start_date = null"
		" where creation < %s and oc_attendance_start_date is not null",
		gate_ran,
	)
