"""M06-01 Exam Registration: one student's courses in one Exam Session, with per-course eligibility and the fee.

Made (and topped up with missing courses) by the bulk registration job, campus.examinations.registration;
the student confirms on /campus-portal, which fixes the fee and queues the exam fee invoice
(campus.examinations.exam_fee). Eligibility is recomputed on every save from the snapshot attendance status
and the detention / debarment flags (registration_rules). Exam dues do not block registration; they block
hall tickets (exam_fee.exam_dues_block).
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.examinations import registration_rules as rules


def registration_name(exam_session, student):
	return f"EXR-{exam_session}-{student}"


class ExamRegistration(Document):
	def autoname(self):
		self.name = registration_name(self.exam_session, self.student)

	def validate(self):
		session = frappe.db.get_value("Exam Session", self.exam_session, ["company", "academic_term"], as_dict=True)
		self.company, self.academic_term = session.company, session.academic_term
		if frappe.db.get_value("Student", self.student, "oc_company") != self.company:
			frappe.throw(_("Student {0} does not belong to {1}.").format(frappe.bold(self.student), frappe.bold(self.company)))
		if self.detained and not (self.detention_reason or "").strip():
			frappe.throw(_("Give the reason for the detention."))
		if self.debarred and not (self.debarment_reason or "").strip():
			frappe.throw(_("Give the reason for the debarment."))
		self.validate_courses()
		self.set_eligibility()

	def validate_courses(self):
		seen = set()
		for row in self.courses:
			if row.course in seen:
				frappe.throw(_("Row {0}: {1} is already registered.").format(row.idx, frappe.bold(row.course)))
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
