"""P2-T25 Student portal: /campus-portal/exams (M06-01 registration, fee, hall ticket, withdrawal)."""

from campus.student_services import exam_portal, portal

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "exams"
	if student:
		context.exams = exam_portal.my_exams(student)
