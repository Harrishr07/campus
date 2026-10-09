"""M07-03 Faculty portal: /campus-portal/faculty/attendance, mark an own or substituted period on a phone
(everyone present, tick the absentees). Posted to campus.faculty.portal.mark_attendance, which checks the period."""

import frappe
from frappe.utils import today

from campus.faculty import portal

no_cache = 1


def get_context(context):
	if not portal.page_context(context, "attendance"):
		return
	course_schedule = frappe.form_dict.get("course_schedule")
	context.roll = portal.attendance_roll(course_schedule) if course_schedule else None
	if not context.roll:
		context.today = portal.my_timetable(today(), today())["periods"]
