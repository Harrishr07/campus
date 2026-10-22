"""M05-07 / M05-13 Faculty portal: /campus-portal/faculty/mentees, the teacher's mentees; with ?student=<id> one
mentee's counselling notes and parent interactions, with forms to add them (campus.faculty.portal_mentoring)."""

import frappe

from campus.faculty import portal, portal_mentoring

no_cache = 1


def get_context(context):
	if not portal.page_context(context, "mentees"):
		return
	context.mentees = portal.my_mentees()
	student = frappe.form_dict.get("student")
	if student:
		try:
			context.record = portal_mentoring.mentee_record(student)
		except frappe.PermissionError:
			context.refused = True
