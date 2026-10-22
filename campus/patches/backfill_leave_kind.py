"""M05-02 Student Leave Applications made before `oc_leave_kind` existed were all counted as medical leave
(the first attendance rules did); keep them so. Re-runnable: once the column exists only blank rows change."""

import frappe

from campus.student_services.setup import setup_student_services


def execute():
	column_existed = frappe.db.has_column("Student Leave Application", "oc_leave_kind")
	setup_student_services()  # a new column is created with DEFAULT 'Leave', which fills every existing row
	if column_existed:
		frappe.db.sql(
			"update `tabStudent Leave Application` set oc_leave_kind = 'Medical' where oc_leave_kind is null or oc_leave_kind = ''"
		)
	else:
		frappe.db.sql("update `tabStudent Leave Application` set oc_leave_kind = 'Medical'")
