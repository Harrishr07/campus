"""P1-T26 Student portal dashboard: /campus-portal."""

import frappe

from campus.campus_messaging.circulars import get_my_circulars
from campus.student_services import portal

no_cache = 1


def get_context(context):
	student = portal.page_context(context)
	context.active = "home"
	if not student:
		return
	context.fees = portal.get_fees(student)
	try:
		context.attendance = portal.get_attendance(student)
	except frappe.ValidationError:  # e.g. the student's regulation has no Attendance Rule yet: the tile shows a dash
		context.attendance = {"academic_term": None, "summary": None}
	results = portal.get_results(student)["results"]
	context.latest_result = results[0] if results else None
	context.onboarding = portal.my_onboarding(student)
	context.pending_circulars = sum(
		1 for c in get_my_circulars() if c["acknowledgement_required"] and not c["acknowledged"]
	)
