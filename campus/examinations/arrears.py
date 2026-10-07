"""M12-02 Arrears: courses a student has sat (or been barred from) and not yet cleared.

Only published Student Results count. A course is an arrear when its latest published outcome is not a Pass
(Fail, SA shortage of attendance or AB absent); a later Pass of the same course clears it.
"""

import frappe
from frappe.utils import now_datetime

PASS = "Pass"


def outstanding_arrears(outcomes):
	"""Courses (sorted) whose last outcome is not a Pass; `outcomes` is [(course, result)] oldest first."""
	latest = dict(outcomes)
	return sorted(course for course, result in latest.items() if result != PASS)


def arrear_courses(student):
	"""Arrear courses of `student` from the published Student Results, oldest result first."""
	result, course_row, session = (frappe.qb.DocType(n) for n in ("Student Result", "Student Result Course", "Exam Session"))
	rows = (
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
	return outstanding_arrears(rows)
