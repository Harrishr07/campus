"""P3-T10 fix 2 (M03-03): a CO Attainment Run no longer carries its per-student input snapshot. Move any value left in
the old `input_snapshot` column into a CO Attainment Snapshot (System Manager, COE, Dean Academics only) and clear the
column, so no response about the run can return a student's marks."""

import frappe

RUN, SNAPSHOT = "CO Attainment Run", "CO Attainment Snapshot"


def execute():
	if not frappe.db.has_column(RUN, "input_snapshot"):
		return
	rows = frappe.db.sql(
		"select name, course_offering, company, input_snapshot from `tabCO Attainment Run` where ifnull(input_snapshot, '') != ''",
		as_dict=True,
	)
	for row in rows:
		if not frappe.db.exists(SNAPSHOT, row.name):
			frappe.get_doc(
				{
					"doctype": SNAPSHOT,
					"co_attainment_run": row.name,
					"course_offering": row.course_offering,
					"company": row.company,
					"snapshot": row.input_snapshot,
				}
			).insert(
				ignore_permissions=True, ignore_links=True
			)  # fmt: skip; a deleted offering must not stop the migrate
	frappe.db.sql("update `tabCO Attainment Run` set input_snapshot = null")
