"""M12-02, M06-08 Mark Sheet Entry: CIA and ESE marks of the students of one course offering in an Exam Session.

Refused once the session is Published. ESE marks and the ESE absent flag change only while the session is in
Marks Entry; CIA may be entered while it is still Draft. When the offering has a CIA Schedule, the CIA column
is consolidated from the question-wise marks (campus.examinations.cia) and locks at the schedule's entry
deadline unless a CIA Unlock Request is approved. Who may edit: campus.examinations.access.

M06-04: a row whose ESE came from the script's valuations (campus.examinations.valuation) keeps it; only the
valuation write-back may change it.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from campus.examinations import cia
from campus.examinations.courses import offering_course, student_limits

MARKS_ENTRY, PUBLISHED = "Marks Entry", "Published"


class MarkSheetEntry(Document):
	def before_validate(self):
		if self.is_new() and not self.marks and self.course_offering:
			members = frappe.get_all(
				"Student Group Student",
				{"parent": self.course_offering, "active": 1},
				pluck="student",
				order_by="group_roll_number, student",
			)
			for student in members:
				self.append("marks", {"student": student})

	def validate(self):
		session = frappe.db.get_value(
			"Exam Session", self.exam_session, ["company", "academic_term", "status"], as_dict=True
		)
		if session.status == PUBLISHED:
			frappe.throw(_("Marks cannot be changed once the Exam Session is published."))
		self.validate_offering(session)
		course = offering_course(self.course_offering)
		if not course["course_type"]:
			frappe.throw(_("Internal Only courses are not graded by the Result Run."))
		if session.status != MARKS_ENTRY:
			self.check_ese_unchanged()
		self.keep_valued_ese()
		self.apply_cia()
		self.validate_marks(course)

	def validate_offering(self, session):
		group = frappe.db.get_value(
			"Student Group", self.course_offering, ["group_based_on", "oc_company", "academic_term"], as_dict=True
		)
		if group.group_based_on != "Course" or group.oc_company != session.company or group.academic_term != session.academic_term:
			frappe.throw(_("The offering must be a course of the session's company and academic term."))
		if frappe.db.exists(
			"Mark Sheet Entry",
			{"exam_session": self.exam_session, "course_offering": self.course_offering, "name": ["!=", self.name]},
		):
			frappe.throw(_("A Mark Sheet Entry already exists for this session and offering."))

	def check_ese_unchanged(self):
		before = {} if self.is_new() else {r.student: r for r in self.get_doc_before_save().marks}
		for row in self.marks:
			old = before.get(row.student)
			if (row.ese or 0, row.absent or 0) != ((old.ese or 0, old.absent or 0) if old else (0, 0)):
				frappe.throw(_("ESE marks can only be entered while the Exam Session is in Marks Entry."))

	def keep_valued_ese(self):
		if self.flags.valuation_write_back:
			return
		before = {} if self.is_new() else {r.student: r for r in self.get_doc_before_save().marks}
		for row in self.marks:
			old = before.get(row.student)
			row.ese_from_valuation = old.ese_from_valuation if old else 0
			if row.ese_from_valuation and (flt(row.ese), row.absent or 0) != (flt(old.ese), old.absent or 0):
				frappe.throw(
					_("Row {0}: the ESE of {1} is the final mark of its valuations and cannot be edited.").format(
						row.idx, row.student
					)
				)

	def apply_cia(self):
		"""Consolidate CIA from the question marks while open; refuse CIA changes while locked."""
		self.cia_schedule = cia.schedule_of(self.course_offering)
		if not self.cia_schedule:
			return
		before = None if self.is_new() else self.get_doc_before_save()
		if self.flags.cia_final_consolidation or cia.lock_state(self.cia_schedule) != cia.LOCKED:
			cia.SheetCIA(self, self.cia_schedule).refresh()
		elif cia.cia_snapshot(self) != cia.cia_snapshot(before):
			frappe.throw(
				_("CIA marks of {0} locked at the entry deadline. Edits need an approved CIA Unlock Request.").format(
					frappe.bold(self.course_offering)
				),
				title=_("CIA Locked"),
			)

	def validate_marks(self, course):
		members = set(student_group_students(self.course_offering))
		seen = set()
		for row in self.marks:
			if row.student not in members or row.student in seen:
				frappe.throw(_("Row {0}: {1} is not a member of the offering, or is listed twice.").format(row.idx, row.student))
			seen.add(row.student)
			if row.absent:  # absent from the ESE; consolidated CIA is kept (carried forward under R2022)
				row.ese = 0
				row.cia = row.cia if self.cia_schedule else 0
				continue
			limits = student_limits(row.student, course)
			if not (0 <= flt(row.cia) <= limits["cia_max"] and 0 <= flt(row.ese) <= limits["ese_max"]):
				frappe.throw(
					_("Row {0}: CIA must lie within 0-{1} and ESE within 0-{2}.").format(
						row.idx, limits["cia_max"], limits["ese_max"]
					)
				)


def student_group_students(offering):
	return frappe.get_all("Student Group Student", {"parent": offering, "active": 1}, pluck="student")
