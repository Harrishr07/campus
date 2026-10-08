"""M06-04 Dummy numbers: one random number per student who sat a course in an Exam Session.

Students seated for the course in the session's Seating Plans and not marked absent get a number drawn with
`secrets` (valuation_rules.dummy_numbers), checked against every number in use and unique in the database.
Only Exam Confidential generates or reads them (valuation_access). The lookups below join dummy numbers to
students for the server only: their results never go back to an examiner.
"""

import frappe
from frappe import _

from campus.examinations import valuation_rules
from campus.examinations.valuation_access import DUMMY_NUMBER_MAP, require_confidential

PUBLISHED = "Published"
SCRIPT_FIELDS = ["name", "dummy_number", "exam_session", "course", "student", "final_ese"]


@frappe.whitelist(methods=["POST"])
def generate_dummy_numbers(exam_session, course):
	"""Exam Confidential: number the scripts of `course` in `exam_session`; returns how many were added."""
	return generate(exam_session, course)


def generate(exam_session, course):
	"""Add numbers for the course's present students who have none; existing numbers are kept."""
	require_confidential()
	status = frappe.db.get_value("Exam Session", exam_session, "status", for_update=True)  # one run at a time
	if not status:
		frappe.throw(_("Exam Session {0} does not exist.").format(exam_session))
	if status == PUBLISHED:
		frappe.throw(_("The Exam Session is published."))
	numbered = set(
		frappe.qb.get_query(
			DUMMY_NUMBER_MAP, filters={"exam_session": exam_session, "course": course}, fields=["student"], for_update=True
		).run(pluck=True)
	)
	students = [s for s in present_students(exam_session, course) if s not in numbered]
	taken = set(frappe.get_all(DUMMY_NUMBER_MAP, pluck="dummy_number"))
	for student, number in zip(students, valuation_rules.dummy_numbers(len(students), taken)):
		frappe.get_doc(
			{"doctype": DUMMY_NUMBER_MAP, "exam_session": exam_session, "course": course, "student": student, "dummy_number": number}
		).insert(ignore_permissions=True)  # fmt: skip
	return len(students)


def present_students(exam_session, course):
	plan, seat = frappe.qb.DocType("Seating Plan"), frappe.qb.DocType("Seating Plan Seat")
	rows = (
		frappe.qb.from_(seat)
		.join(plan).on(plan.name == seat.parent)
		.select(seat.student).distinct()
		.where(
			(seat.parenttype == "Seating Plan") & (plan.exam_session == exam_session) & (seat.course == course)
			& (seat.absent == 0) & seat.student.isnotnull()
		)
		.run(pluck=True)
	)  # fmt: skip
	return sorted(rows)


# ---- server-side joins (never returned to examiners) -------------------------------------------


def script(dummy_number, for_update=False):
	"""The map row of a dummy number (name, dummy_number, exam_session, course, student, final_ese), or None."""
	return frappe.db.get_value(
		DUMMY_NUMBER_MAP,
		{"dummy_number": dummy_number},
		SCRIPT_FIELDS,
		as_dict=True,
		for_update=for_update,
	)


def numbers_of(exam_session, course):
	return frappe.get_all(DUMMY_NUMBER_MAP, {"exam_session": exam_session, "course": course}, pluck="dummy_number")
