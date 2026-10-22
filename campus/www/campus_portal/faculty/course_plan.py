"""M07-01 Faculty portal: /campus-portal/faculty/course-plan, read-only per own offering (curriculum periods a week,
periods scheduled and held, course topics). There is no lesson plan DocType yet."""

from campus.faculty import portal

no_cache = 1


def get_context(context):
	if portal.page_context(context, "course_plan"):
		context.plan = portal.course_plan()
