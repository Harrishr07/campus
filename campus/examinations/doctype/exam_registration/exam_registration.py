"""M06-01 Exam Registration: one student's courses in one Exam Session, with per-course eligibility and the fee.

Made (and topped up with missing courses) by the bulk registration job, campus.examinations.registration;
the student confirms on /campus-portal, which fixes the fee and queues the exam fee invoice
(campus.examinations.exam_fee). Eligibility is recomputed on every save from the snapshot attendance status
and the detention / debarment flags (registration_rules). Exam dues do not block registration; they block
hall tickets (exam_fee.exam_dues_block).

The confirmation and fee fields and each course row's course, offering and kind are server-owned: only
registration.confirm (flags.server_fields) sets the former, and only the bulk job sets the latter (on a new row).
A hand edit of either is refused. A new registration is refused for a student whose examination mode (Autonomous /
Affiliated, M06-10) is not the session's.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, flt

from campus.examinations import registration_rules as rules
from campus.examinations.affiliation import AUTONOMOUS, examination_mode

SERVER_FIELDS = ("confirmed", "confirmed_on", "late_days", "exam_fee", "late_fee", "fee_total", "fee_invoice")
ROW_FIELDS = ("course", "course_offering", "kind")


def registration_name(exam_session, student):
	return f"EXR-{exam_session}-{student}"


class ExamRegistration(Document):
	def autoname(self):
		self.name = registration_name(self.exam_session, self.student)

	def validate(self):
		session = frappe.db.get_value(
			"Exam Session", self.exam_session, ["company", "academic_term", "examination_mode"], as_dict=True
		)
		self.company, self.academic_term = session.company, session.academic_term
		if frappe.db.get_value("Student", self.student, "oc_company") != self.company:
			frappe.throw(
				_("Student {0} does not belong to {1}.").format(
					frappe.bold(self.student), frappe.bold(self.company)
				)
			)
		if self.is_new():
			self.check_mode(session.examination_mode or AUTONOMOUS)
		if self.detained and not (self.detention_reason or "").strip():
			frappe.throw(_("Give the reason for the detention."))
		if self.debarred and not (self.debarment_reason or "").strip():
			frappe.throw(_("Give the reason for the debarment."))
		self.guard_server_fields()
		self.validate_courses()
		self.set_eligibility()

	def check_mode(self, session_mode):
		"""M06-10: a student is registered only in a session of their own examination mode."""
		mode = examination_mode(self.student)
		if mode != session_mode:
			frappe.throw(
				_("{0} writes {1} examinations; {2} is an {3} session.").format(
					frappe.bold(self.student), _(mode), frappe.bold(self.exam_session), _(session_mode)
				)
			)

	def guard_server_fields(self):
		if self.flags.server_fields:
			return
		before = self.get_doc_before_save()
		old = before or frappe._dict()
		changed = [f for f in SERVER_FIELDS if _plain(self.get(f)) != _plain(old.get(f))]
		old_rows = {row.name: row for row in before.courses} if before else {}
		changed += [
			f"{row.idx}.{f}"
			for row in self.courses
			if row.name in old_rows
			for f in ROW_FIELDS
			if _plain(row.get(f)) != _plain(old_rows[row.name].get(f))
		]
		if changed:
			frappe.throw(
				_("{0} of an Exam Registration are set by the server only.").format(", ".join(changed)),
				title=_("Server-owned fields"),
			)

	def validate_courses(self):
		seen = set()
		for row in self.courses:
			if row.course in seen:
				frappe.throw(
					_("Row {0}: {1} is already registered.").format(row.idx, frappe.bold(row.course))
				)
			seen.add(row.course)
		before = self.get_doc_before_save()
		if before and before.confirmed and {r.course for r in before.courses} != seen:
			frappe.throw(_("The courses of a confirmed Exam Registration cannot change; its fee is fixed."))

	def set_eligibility(self):
		shortage = self.attendance_status == "Shortage"
		for row in self.courses:
			row.eligibility = rules.course_eligibility(row.kind, shortage, self.detained, self.debarred)

	def eligible_courses(self):
		return [row for row in self.courses if row.eligibility == rules.ELIGIBLE]


def _plain(value):
	"""A comparable form of a field value: blanks alike, numbers by value."""
	if not value:
		return None
	return flt(value) if isinstance(value, int | float) else cstr(value)
