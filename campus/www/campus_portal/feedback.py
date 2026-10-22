"""P3-T07 Student portal: /campus-portal/feedback lists the open feedback campaigns the student or parent may still answer."""

from campus.iqac import feedback
from campus.student_services import portal

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "feedback"
	if student:
		context.campaigns = feedback.open_campaigns_for()
