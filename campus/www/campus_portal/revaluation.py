"""P2-T25 Student portal: /campus-portal/revaluation (M06-06 photocopy, revaluation and review, with the fee)."""

from campus.student_services import exam_portal, portal

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "revaluation"
	if student:
		context.revaluations = exam_portal.my_revaluations(student)
