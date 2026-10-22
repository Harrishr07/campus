"""M07-03 Faculty portal: /campus-portal/faculty/leave, apply for the teacher's own HRMS Leave Application and list them.
Posted to campus.faculty.portal.apply_leave, which takes the Employee from the session."""

from campus.faculty import portal

no_cache = 1


def get_context(context):
	if portal.page_context(context, "leave"):
		context.leave_types = portal.leave_types()
		context.leaves = portal.my_leaves()
