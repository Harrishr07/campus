"""M05-02 Student Leave Applications made before `oc_leave_kind` existed were all counted as medical leave
(the first attendance rules did); keep them so. Re-runnable."""

import frappe

from campus.student_services.setup import setup_student_services


def execute():
	setup_student_services()
	frappe.db.sql(
		"update `tabStudent Leave Application` set oc_leave_kind = 'Medical' where oc_leave_kind is null or oc_leave_kind = ''"
	)
