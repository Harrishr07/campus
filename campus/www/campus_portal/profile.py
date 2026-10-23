"""L-08 Student portal: /campus-portal/profile (M05-11 the student's own 360 view)."""

from campus.student_services import portal, student_360

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "profile"
	if student:
		context.view = student_360.portal_view(student)
