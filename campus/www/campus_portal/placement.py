"""M14-01 Student portal: /campus-portal/placement (open drives, live eligibility, opt-in)."""

from campus.placement import portal
from campus.student_services import portal as student_portal

no_cache = 1


def get_context(context):
	student = student_portal.page_context(context)
	context.active = "placement"
	if student:
		context.placement = portal.my_drives(student)
