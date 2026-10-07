"""P1-T26 Student portal: /campus-portal/grievances (M05-06 raise and list)."""

from campus.student_services import portal

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "grievances"
	if student:
		context.categories = portal.grievance_categories()
		context.grievances = portal.my_grievances(student)["grievances"]
