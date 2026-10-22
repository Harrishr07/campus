"""P1-T26 Student portal: /campus-portal/circulars (T11 feed; acknowledgement is by the session user)."""

from campus.campus_messaging.circulars import get_my_circulars
from campus.student_services import portal

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "circulars"
	if student:
		context.circulars = portal.clean_circular_body(get_my_circulars())
