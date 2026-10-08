"""M06-04 Dummy numbers: one random number per student who sat a course in an Exam Session.

Students seated for the course in the session's Seating Plans and not marked absent get a number drawn with
`secrets` (valuation_rules.dummy_numbers), checked against every number in use and unique in the database (a
number another run took meanwhile is redrawn).
Only Exam Confidential generates or reads them (valuation_access). The lookups below join dummy numbers to
students for the server only: their results never go back to an examiner.
"""

import frappe
from frappe import _

from campus.examinations import valuation_rules
from campus.examinations.valuation_access import DUMMY_NUMBER_MAP, require_confidential

PUBLISHED = "Published"
SCRIPT_FIELDS = ["name", "dummy_number", "exam_session", "course", "student", "void", "final_ese"]


@frappe.whitelist(methods=["POST"])
def generate_dummy_numbers(exam_session, course):
	"""Exam Confidential: number the scripts of `course` in `exam_session`; returns how many were added."""
	return generate(exam_session, course)


def generate(exam_session, course):
	"""Add numbers for the course's present students who have none; existing numbers are kept.

	A student marked absent after the draw has the number voided (and restored if the mark is lifted)."""
	require_confidential()
	status = frappe.db.get_value("Exam Session", exam_session, "status", for_update=True)  # one run at a time
	if not status:
		frappe.throw(_("Exam Session {0} does not exist.").format(exam_session))
	if status == PUBLISHED:
		frappe.throw(_("The Exam Session is published."))
	rows = frappe.qb.get_query(
		DUMMY_NUMBER_MAP, filters={"exam_session": exam_session, "course": course}, fields=["name", "student", "void"], for_update=True
	).run(as_dict=True)  # fmt: skip
	present = present_students(exam_session, course)
	for row in rows:
		void = int(row.student not in present)
		if void != row.void:
			frappe.db.set_value(DUMMY_NUMBER_MAP, row.name, "void", void)
	numbered = {row.student for row in rows}
	students = [s for s in sorted(present) if s not in numbered]
	taken = set(frappe.get_all(DUMMY_NUMBER_MAP, pluck="dummy_number"))
	for student, number in zip(students, valuation_rules.dummy_numbers(len(students), taken)):
		insert_number(exam_session, course, student, number, taken)
	return len(students)


def insert_number(exam_session, course, student, number, taken, attempts=5):
	"""Insert the map row; a number taken by another run meanwhile (DB unique key) is redrawn."""
	for _attempt in range(attempts):
		doc = frappe.get_doc(
			{"doctype": DUMMY_NUMBER_MAP, "exam_session": exam_session, "course": course, "student": student, "dummy_number": number}
		)  # fmt: skip
		try:
			return doc.insert(ignore_permissions=True)
		except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
			frappe.clear_messages()
			taken.add(number)
			number = valuation_rules.dummy_numbers(1, taken)[0]
	frappe.throw(_("No free dummy number could be drawn. Please try again."))


def present_students(exam_session, course):
	"""Students seated for the course in the session and not marked absent in any of its seats."""
	plan, seat = frappe.qb.DocType("Seating Plan"), frappe.qb.DocType("Seating Plan Seat")
	rows = (
		frappe.qb.from_(seat)
		.join(plan).on(plan.name == seat.parent)
		.select(seat.student, seat.absent)
		.where(
			(seat.parenttype == "Seating Plan") & (plan.exam_session == exam_session) & (seat.course == course)
			& seat.student.isnotnull()
		)
		.run(as_dict=True)
	)  # fmt: skip
	return {r.student for r in rows} - {r.student for r in rows if r.absent}


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
	"""The course's live (not void) dummy numbers in the session."""
	return frappe.get_all(DUMMY_NUMBER_MAP, {"exam_session": exam_session, "course": course, "void": 0}, pluck="dummy_number")
