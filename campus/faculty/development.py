"""M07-05 Faculty development counts for one company and academic year, shared by the reports and the IQAC data points.

NAAC 6.3.4: FDPs attended. A row is a teacher present at a submitted HRMS Training Event flagged oc_is_fdp that started in
the year. NAAC 6.3.2: financial support to attend conferences and workshops and towards membership of professional bodies.
A row is a verified Faculty Achievement of type Conference or Membership dated in the year with a support amount above zero.
Teachers are those of campus.faculty.staffing.teachers (read with the session user's permissions), so a user limited to a
department or company sees only that part.
"""

import frappe
from frappe.utils import add_days

from campus.faculty import staffing

SUPPORTED_TYPES = ("Conference", "Membership")


def fdp_attendances(company, academic_year, department=None):
	"""One row per teacher per FDP attended: employee, employee_name, department, training_event, start_time, end_time."""
	teachers = {t.name: t for t in staffing.teachers(company, academic_year, department)}
	if not teachers:
		return []
	start, end = staffing.year_bounds(academic_year)
	event, attendee = frappe.qb.DocType("Training Event"), frappe.qb.DocType("Training Event Employee")
	rows = (
		frappe.qb.from_(attendee)
		.join(event)
		.on(attendee.parent == event.name)
		.select(attendee.employee, event.name, event.start_time, event.end_time)
		.where(attendee.employee.isin(list(teachers)) & (attendee.attendance == "Present"))
		.where((event.docstatus == 1) & (event.oc_is_fdp == 1) & (event.event_status != "Cancelled"))
		.where((event.start_time >= start) & (event.start_time < add_days(end, 1)))
		.orderby(attendee.employee)
		.orderby(event.start_time)
		.run()
	)  # fmt: skip
	return [
		{
			"employee": employee, "employee_name": teachers[employee].employee_name, "department": teachers[employee].department,
			"training_event": name, "start_time": start_time, "end_time": end_time,
		}
		for employee, name, start_time, end_time in rows
	]  # fmt: skip


def supported_achievements(company, academic_year, department=None):
	"""One row per supported Faculty Achievement: employee, employee_name, department, achievement_type, title, date, amount."""
	teachers = {t.name: t for t in staffing.teachers(company, academic_year, department)}
	if not teachers:
		return []
	start, end = staffing.year_bounds(academic_year)
	rows = frappe.get_list(
		"Faculty Achievement",
		{
			"employee": ["in", list(teachers)], "verified": 1, "achievement_type": ["in", SUPPORTED_TYPES],
			"financial_support_amount": [">", 0], "achievement_date": ["between", [start, end]],
		},
		["name", "employee", "achievement_type", "title", "achievement_date", "financial_support_amount"],
		order_by="employee, achievement_date, name", limit_page_length=0,
	)  # fmt: skip
	return [
		{
			"name": r.name, "employee": r.employee, "employee_name": teachers[r.employee].employee_name,
			"department": teachers[r.employee].department, "achievement_type": r.achievement_type, "title": r.title,
			"date": r.achievement_date, "amount": r.financial_support_amount,
		}
		for r in rows
	]  # fmt: skip
