"""M06-08 CIA on the Mark Sheet Entry: question rows from the CIA Schedule, the lock at the entry deadline,
approved unlock windows and consolidation into the converted CIA column (with R2026 attendance marks).

A sheet whose offering has a CIA Schedule keeps one Mark Sheet CIA Mark per student and schedule question.
Before the deadline (or inside an approved CIA Unlock Request window) every save re-syncs those rows from the
schedule and recomputes each student's CIA; otherwise the CIA data is frozen. The hourly lock job consolidates
each sheet once more after its deadline, so attendance marks are taken as at the lock.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from campus.examinations import cia_rules
from campus.examinations.courses import offering_course
from campus.student_services.api import attendance_marks

OPEN, LOCKED, UNLOCKED = "Open", "Locked", "Unlocked"
SCHEDULE, UNLOCK, TEMPLATE = "CIA Schedule", "CIA Unlock Request", "CIA Component Template"


def schedule_of(offering):
	return frappe.db.get_value(SCHEDULE, {"course_offering": offering})


def lock_state(schedule):
	"""Open before the entry deadline, Unlocked inside an approved unlock window, else Locked."""
	deadline = frappe.db.get_value(SCHEDULE, schedule, "entry_deadline")
	if now_datetime() <= get_datetime(deadline):
		return OPEN
	return UNLOCKED if active_unlock(schedule) else LOCKED


def active_unlock(schedule):
	"""The approved (submitted) CIA Unlock Request of `schedule` whose window is still open, if any."""
	return frappe.db.get_value(
		UNLOCK, {"cia_schedule": schedule, "docstatus": 1, "unlock_until": [">=", now_datetime()]}, "name"
	)


def template_for(offering):
	"""The CIA Component Template of the offering's curriculum regulation and course type."""
	curriculum = frappe.db.get_value("Student Group", offering, "oc_curriculum")
	regulation = curriculum and frappe.db.get_value("Curriculum", curriculum, "regulation")
	course_type = offering_course(offering)["course_type"]
	template = frappe.db.get_value(TEMPLATE, {"regulation": regulation, "course_type": course_type})
	if not template:
		frappe.throw(
			_("No CIA Component Template for regulation {0} and course type {1}.").format(
				frappe.bold(regulation), frappe.bold(course_type or _("Internal Only"))
			)
		)
	return template


class SheetCIA:
	"""The CIA part of one Mark Sheet Entry under its CIA Schedule."""

	def __init__(self, sheet, schedule):
		self.sheet = sheet
		self.schedule = frappe.get_doc(SCHEDULE, schedule)
		self.template = frappe.get_doc(TEMPLATE, self.schedule.template)

	def refresh(self):
		"""Re-sync the question rows from the schedule, check them and recompute every student's CIA."""
		self.sync_questions()
		self.validate_question_marks()
		self.consolidate()

	def sync_questions(self):
		"""One row per student and schedule question, tags copied from the schedule; rows of removed
		questions or students are dropped (the Version history keeps them)."""
		questions = {(q.component, q.question): q for q in self.schedule.questions}
		students = [row.student for row in self.sheet.marks]
		existing = {(r.student, r.component, r.question): r for r in self.sheet.get("cia_marks", [])}
		rows = []
		for student in students:
			for key, question in questions.items():
				row = existing.get((student, *key)) or frappe._dict(student=student, component=key[0], question=key[1])
				row.update({"max_marks": question.max_marks, "course_outcome": question.course_outcome, "bloom_level": question.bloom_level})
				rows.append(row)
		self.sheet.set("cia_marks", rows)

	def validate_question_marks(self):
		absent = {(r.student, r.component) for r in self.sheet.cia_marks if r.absent}
		for row in self.sheet.cia_marks:
			if (row.student, row.component) in absent:  # absent from an assessment: every question of it
				row.absent, row.marks = 1, 0
			elif not 0 <= (row.marks or 0) <= row.max_marks:
				frappe.throw(
					_("CIA row {0}: {1} {2} {3} must lie within 0-{4}.").format(
						row.idx, row.student, row.component, row.question, row.max_marks
					)
				)

	def consolidate(self):
		totals = cia_rules.component_totals((r.student, r.component, r.marks, r.absent) for r in self.sheet.cia_marks)
		components = [(c.component, c.max_marks, c.weight) for c in self.template.components]
		for row in self.sheet.marks:
			marks = {c: totals.get((row.student, c), 0.0) for c, _max, _weight in components}
			row.cia_attendance = self.attendance_marks(row.student)
			row.cia = cia_rules.converted_cia(components, marks, row.cia_attendance, self.template.round_to_integer)

	def attendance_marks(self, student):
		if not self.template.includes_attendance_marks:
			return 0
		return min(attendance_marks(student, self.sheet.course_offering)["marks"], self.template.attendance_max)


def cia_snapshot(sheet):
	"""What the lock freezes: the question marks and the consolidated CIA columns."""
	if not sheet:
		return None
	questions = sorted(
		(r.student, r.component, r.question, float(r.marks or 0), int(r.absent or 0)) for r in sheet.get("cia_marks", [])
	)
	columns = sorted((r.student, float(r.cia or 0), float(r.cia_attendance or 0)) for r in sheet.marks)
	return questions, columns


def lock_due_schedules():
	"""Hourly: consolidate the sheets of schedules whose deadline has passed and stamp them locked."""
	for schedule in frappe.get_all(
		SCHEDULE, {"entry_deadline": ["<", now_datetime()], "locked_on": ["is", "not set"]}, pluck="name"
	):
		try:
			lock_schedule(schedule)
			frappe.db.commit()  # nosemgrep: one schedule per transaction, a failure must not undo the others
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=_("CIA lock failed for {0}").format(schedule), message=frappe.get_traceback())


def lock_schedule(schedule):
	for sheet in frappe.get_all("Mark Sheet Entry", {"cia_schedule": schedule}, ["name", "exam_session"]):
		if frappe.db.get_value("Exam Session", sheet.exam_session, "status") == "Published":
			continue  # a published sheet is final already
		doc = frappe.get_doc("Mark Sheet Entry", sheet.name)
		doc.flags.cia_final_consolidation = True
		doc.save(ignore_permissions=True)
	frappe.db.set_value(SCHEDULE, schedule, "locked_on", now_datetime())
