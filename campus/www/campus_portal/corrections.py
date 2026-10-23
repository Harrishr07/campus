"""L-08 Student portal: /campus-portal/corrections (M05-11 raise a record correction and follow it)."""

from campus.student_services import corrections, portal

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "corrections"
	if student:
		context.fields = corrections.correctable_fields(student)
		context.guardians = corrections.student_guardians(student)
		context.corrections = corrections.my_corrections(student)["corrections"]
