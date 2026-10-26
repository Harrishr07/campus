"""M06-08 CIA entry on the faculty portal (P2-T11): the Mark Sheet Entries of offerings the teacher instructs (the T13
rule: Student Group instructor), saved through the Mark Sheet Entry controller, which consolidates and applies the
CIA lock. Under a CIA Schedule marks are question-wise; a schedule without questions shows the consolidated CIA
read-only; without a schedule the CIA column is entered.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from campus.examinations.api import cia_lock_state, instructed_offerings, instructor_users
from campus.faculty.portal import require_faculty

SHEET, CIA_SCHEDULE = "Mark Sheet Entry", "CIA Schedule"


@frappe.whitelist()
def my_mark_sheets():
	"""Mark Sheet Entries of the offerings the caller instructs."""
	require_faculty()
	offerings = [o for o in instructed_offerings(frappe.session.user) if o]
	sheets = frappe.get_all(
		SHEET,
		{"course_offering": ["in", offerings or [""]]},
		["name", "exam_session", "course_offering", "course"],
		order_by="exam_session, course_offering",
	)
	for sheet in sheets:
		sheet.session_status = frappe.db.get_value("Exam Session", sheet.exam_session, "status")
	return sheets


def own_sheet(mark_sheet, ptype):
	require_faculty()
	offering = frappe.db.get_value(SHEET, mark_sheet, "course_offering")
	if not offering or frappe.session.user not in instructor_users(offering):
		frappe.throw(_("You do not instruct this offering."), frappe.PermissionError)
	doc = frappe.get_doc(SHEET, mark_sheet)
	doc.check_permission(ptype)
	return doc


@frappe.whitelist()
def cia_sheet(mark_sheet):
	"""The sheet's students with their CIA question marks (or CIA column), the lock state and whether it is editable."""
	doc = own_sheet(mark_sheet, "read")
	schedule = frappe.db.get_value(CIA_SCHEDULE, {"course_offering": doc.course_offering})
	lock_state = cia_lock_state(schedule) if schedule else None
	published = frappe.db.get_value("Exam Session", doc.exam_session, "status") == "Published"
	questions = cia_questions(schedule)
	cells = {(r.student, r.component, r.question): r for r in doc.get("cia_marks", [])}
	students = []
	for row in doc.marks:
		marks = [cells.get((row.student, q.component, q.question)) for q in questions]
		students.append(
			{
				"student": row.student, "student_name": row.student_name, "cia": row.cia, "cia_attendance": row.cia_attendance,
				"marks": [{"marks": m.marks if m else None, "absent": m.absent if m else 0} for m in marks],
			}
		)  # fmt: skip
	return {
		"name": doc.name, "exam_session": doc.exam_session, "course_offering": doc.course_offering, "course": doc.course,
		"cia_schedule": schedule, "lock_state": lock_state, "published": published,
		"editable": not published and lock_state != "Locked", "entry": entry_mode(schedule, questions),
		"questions": questions, "students": students,
	}  # fmt: skip


def entry_mode(schedule, questions):
	"""questions: marks per CIA Schedule question; consolidated: a schedule without questions, CIA shown read-only;
	column: no schedule, the CIA column is entered."""
	if not schedule:
		return "column"
	return "questions" if questions else "consolidated"


def cia_questions(schedule):
	if not schedule:
		return []
	return frappe.get_all(
		"CIA Schedule Question",
		{"parent": schedule, "parenttype": CIA_SCHEDULE},
		["component", "question", "max_marks"],
		order_by="idx",
	)


@frappe.whitelist(methods=["POST"])
def save_cia_marks(mark_sheet, marks):
	"""Save CIA marks on the caller's own sheet: rows of {student, component, question, marks, absent} under a CIA
	Schedule, else {student, cia}. The Mark Sheet Entry controller checks ranges and refuses edits once locked."""
	doc = own_sheet(mark_sheet, "write")
	rows = frappe.parse_json(marks) if isinstance(marks, str) else marks
	if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
		frappe.throw(_("Give the marks as a list of rows."))
	schedule = frappe.db.get_value(CIA_SCHEDULE, {"course_offering": doc.course_offering})
	(apply_question_marks if schedule else apply_cia_column)(doc, rows, schedule)
	doc.save()
	return {row.student: row.cia for row in doc.marks}


def apply_question_marks(doc, rows, schedule):
	students = {r.student for r in doc.marks}
	questions = {(q.component, q.question) for q in cia_questions(schedule)}
	cells = {(r.student, r.component, r.question): r for r in doc.get("cia_marks", [])}
	for row in rows:
		key = (row.get("student"), row.get("component"), row.get("question"))
		if key[0] not in students or key[1:] not in questions:
			frappe.throw(_("No CIA question {1} {2} for {0} on this sheet.").format(*key))
		values = {"marks": flt(row.get("marks")), "absent": cint(row.get("absent"))}
		if key in cells:
			cells[key].update(values)
		else:  # the controller's sync adds the CO / Bloom tags
			doc.append("cia_marks", {"student": key[0], "component": key[1], "question": key[2], **values})


def apply_cia_column(doc, rows, _schedule):
	by_student = {r.student: r for r in doc.marks}
	for row in rows:
		if row.get("student") not in by_student:
			frappe.throw(_("{0} is not on this sheet.").format(row.get("student")))
		if row.get("cia") in (None, ""):
			continue  # a blank input is not an entry of 0
		by_student[row["student"]].cia = flt(row.get("cia"))
