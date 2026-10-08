"""M07-03 A substitute marks attendance for the substituted period, and only that period.

The grant is the Confirmed Substitution itself: it names one Course Schedule and one user. The Student Attendance records
are written by the server for exactly that schedule, for students of its Student Group; the substitute's roles never
change, so nothing else is opened to them. Teachers who already hold the attendance role (Academics User) can mark
attendance as before.
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

LIVE_GRANT = "Confirmed"


def granting_substitution(user, course_schedule):
	"""Name of the Confirmed Substitution that gives `user` this period, or None."""
	return frappe.db.get_value("Substitution", {"course_schedule": course_schedule, "substitute_user": user, "status": LIVE_GRANT})


def can_mark(user, course_schedule):
	return bool(user) and bool(granting_substitution(user, course_schedule))


def mark(substitution, present=None, absent=None):
	"""Record Present / Absent for students of the substituted period's Student Group. Returns the attendance names."""
	present, absent = as_list(present), as_list(absent)
	course_schedule = frappe.db.get_value("Substitution", substitution, "course_schedule")
	if not course_schedule or granting_substitution(frappe.session.user, course_schedule) != substitution:
		frappe.throw(_("You are not the confirmed substitute for this period."), frappe.PermissionError)
	schedule = frappe.db.get_value("Course Schedule", course_schedule, ["student_group", "schedule_date"], as_dict=True)
	if getdate(schedule.schedule_date) > getdate(today()):
		frappe.throw(_("Attendance cannot be marked for a period that has not happened yet."))
	roll = dict(frappe.get_all("Student Group Student", {"parent": schedule.student_group, "active": 1}, ["student", "student_name"], as_list=True))
	chosen = [*present, *absent]
	if len(set(chosen)) != len(chosen):
		frappe.throw(_("A student is listed more than once."))
	outsiders = [s for s in chosen if s not in roll]
	if outsiders:
		frappe.throw(_("Not in {0}: {1}").format(schedule.student_group, ", ".join(outsiders)))
	return [record(s, roll[s], status, course_schedule, schedule) for status, students in (("Present", present), ("Absent", absent)) for s in students]


def record(student, student_name, status, course_schedule, schedule):
	"""Create the attendance, or correct an existing submitted one of this student and period: a different status
	cancels it and writes a new record (same grant, same checks); the same status changes nothing."""
	existing = frappe.db.get_value("Student Attendance", {"student": student, "course_schedule": course_schedule, "docstatus": 1}, ["name", "status"], as_dict=True)
	if existing and existing.status == status:
		return existing.name
	if existing:
		old = frappe.get_doc("Student Attendance", existing.name)
		old.flags.ignore_permissions = True
		old.cancel()
	doc = frappe.get_doc(
		{
			"doctype": "Student Attendance", "student": student, "student_name": student_name, "status": status,
			"course_schedule": course_schedule, "student_group": schedule.student_group, "date": schedule.schedule_date,
		}
	)  # fmt: skip
	doc.flags.ignore_permissions = True  # the Confirmed Substitution is the permission, resolved above on the server
	doc.insert()
	doc.submit()
	return doc.name


def as_list(value):
	value = frappe.parse_json(value) if isinstance(value, str) else value
	students = list(value or [])
	if not all(isinstance(s, str) for s in students):
		frappe.throw(_("Give the students as a list of Student names."))
	return students
