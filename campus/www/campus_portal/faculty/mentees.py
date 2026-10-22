"""M05-07 Faculty portal: /campus-portal/faculty/mentees, the teacher's mentees, read-only."""

from campus.faculty import portal

no_cache = 1


def get_context(context):
	if portal.page_context(context, "mentees"):
		context.mentees = portal.my_mentees()
