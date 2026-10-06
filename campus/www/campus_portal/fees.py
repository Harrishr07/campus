"""P1-T26 Student portal: /campus-portal/fees."""

from campus.student_services import portal

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "fees"
	if student:
		context.fees = portal.get_fees(student)
