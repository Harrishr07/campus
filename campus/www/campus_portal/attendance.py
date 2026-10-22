"""P1-T26 Student portal: /campus-portal/attendance (?term= picks a term the student studied in)."""

import frappe

from campus.student_services import portal

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "attendance"
	if student:
		context.attendance = portal.get_attendance(student, frappe.form_dict.get("term"))
