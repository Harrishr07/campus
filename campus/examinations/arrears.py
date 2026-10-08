"""M12-02 Arrears: courses a student has sat (or been barred from) and not yet cleared.

Only published Student Results count, and a later Pass of a course clears it. Two views:
- an arrear (arrear_courses, for transcripts and progression) is any course whose latest outcome is not a Pass:
  Fail (U), SA shortage of attendance, AB absent or WD withdrawn;
- a reappearance course (reappearance_courses, for exam registration, M06-01) is the subset written again as an
  arrear in a later session: Fail, AB and WD. An SA course is not one; the student redoes the course first.
"""

import frappe
from frappe.utils import now_datetime

PASS = "Pass"
# Outcomes a reappearance course has (U fail, absent, withdrawn); see the module docstring.
REAPPEAR = ("Fail", "AB", "WD")


def outstanding_arrears(outcomes):
	"""Courses (sorted) whose last outcome is not a Pass; `outcomes` is [(course, result)] oldest first."""
	latest = dict(outcomes)
	return sorted(course for course, result in latest.items() if result != PASS)


def arrear_courses(student):
	"""Arrear courses (sorted) of `student`: latest published outcome anything but a Pass, SA included."""
	return outstanding_arrears(published_outcomes(student))


def reappearance_courses(student):
	"""Reappearance courses (sorted) of `student`: latest published outcome Fail, AB or WD (REAPPEAR), never SA."""
	latest = dict(published_outcomes(student))
	return sorted(course for course, result in latest.items() if result in REAPPEAR)


def published_outcomes(student):
	"""[(course, result)] of `student` from the published Student Results, oldest result first."""
	result, course_row, session = (frappe.qb.DocType(n) for n in ("Student Result", "Student Result Course", "Exam Session"))
	return (
		frappe.qb.from_(result)
		.join(course_row)
		.on((course_row.parent == result.name) & (course_row.parenttype == "Student Result"))
		.join(session)
		.on(session.name == result.exam_session)
		.select(course_row.course, course_row.result)
		.where(result.student == student)
		.where(session.status == "Published")
		.where(session.publish_at <= now_datetime())
		.orderby(session.publish_at)
		.orderby(result.creation)
		.orderby(course_row.idx)
		.run()
	)
