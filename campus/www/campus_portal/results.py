"""P1-T26 Student portal: /campus-portal/results."""

from campus.student_services import portal

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "results"
	if student:
		context.results = portal.get_results(student)["results"]
