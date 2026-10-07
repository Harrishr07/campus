"""P1-T26 Student portal: /campus-portal/certificates (M05-04 request and list)."""

from campus.student_services import portal

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "certificates"
	if student:
		context.types = portal.certificate_types()
		context.certificates = portal.my_certificates(student)["certificates"]
