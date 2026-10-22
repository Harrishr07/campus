"""M12-02 / M06-01 Exam Session: one examination of a company in an academic term (Draft, Marks Entry, Published).

M06-01 adds the registration window (opens, closes = last day without a late fee), the exam dates and the
Exam Schedule (one row per course: date and slot, inside the exam dates).

M06-06: it becomes Published only through campus.examinations.publication.publish_results, on the approving
resolution of a quorate Passing Board meeting; publish_at is the release time.

M06-10: an Affiliated session (examination_mode, set once) is the university's examination of the term: it is
Published by its first University Result Import (campus.examinations.university_import), never by Publish Results.
A company has one session per term and mode, so a college with both kinds of regulations holds two.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, getdate

AFFILIATED = "Affiliated"


class ExamSession(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if before and before.status == "Published" and self.status != "Published":
			frappe.throw(_("A published Exam Session cannot be reopened."))
		if before and before.status == "Published" and get_datetime(before.publish_at) != get_datetime(self.publish_at):
			frappe.throw(_("The publication time of a published Exam Session cannot change."))
		if before and before.status == "Published" and (before.frozen_bands or "") != (self.frozen_bands or ""):
			frappe.throw(_("The relative bands frozen at publication cannot change."))
		if self.status == "Published" and not (before and before.status == "Published") and not self.publication_allowed():
			if self.examination_mode == AFFILIATED:
				frappe.throw(_("An Affiliated session is published by importing the university's results."))
			frappe.throw(_("Results are published with Publish Results, on the approving resolution of a Passing Board meeting."))
		if frappe.db.exists(
			"Exam Session",
			{"company": self.company, "academic_term": self.academic_term, "examination_mode": self.examination_mode, "name": ["!=", self.name]},
		):
			frappe.throw(_("{0} already has an {1} Exam Session for {2}.").format(self.company, _(self.examination_mode), self.academic_term))
		self.validate_dates()
		self.validate_schedule()

	def publication_allowed(self):
		if self.examination_mode == AFFILIATED:
			return bool(self.flags.university_results)
		return bool(self.flags.passing_board_approval)

	def validate_dates(self):
		if self.registration_opens and self.registration_closes and getdate(self.registration_closes) < getdate(self.registration_opens):
			frappe.throw(_("Registration cannot close before it opens."))
		if self.exam_start and self.exam_end and getdate(self.exam_end) < getdate(self.exam_start):
			frappe.throw(_("The exams cannot end before they start."))
		if self.registration_closes and self.exam_start and getdate(self.exam_start) < getdate(self.registration_closes):
			frappe.throw(_("Registration must close before the exams start."))

	def validate_schedule(self):
		if self.schedule and not (self.exam_start and self.exam_end):
			frappe.throw(_("Set the exam dates before the schedule."))
		seen = set()
		for row in self.schedule:
			if row.course in seen:
				frappe.throw(_("Row {0}: {1} is already scheduled.").format(row.idx, frappe.bold(row.course)))
			seen.add(row.course)
			if not getdate(self.exam_start) <= getdate(row.exam_date) <= getdate(self.exam_end):
				frappe.throw(_("Row {0}: the exam of {1} must fall within the exam dates.").format(row.idx, frappe.bold(row.course)))
