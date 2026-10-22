"""P1-T26 Student portal: /campus-portal/leave (M05-02 apply and list)."""

from campus.student_services import portal
from campus.student_services.setup import LEAVE_KINDS

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "leave"
	if student:
		context.leave_kinds = LEAVE_KINDS
		context.leaves = portal.my_leaves(student)["leaves"]
