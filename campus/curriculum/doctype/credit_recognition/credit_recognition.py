"""M03-09 (thin cut for M05-15) Credit Recognition: a course of a student's curriculum cleared by equivalence, transfer,
waiver or external (MOOC / NPTEL) credit, with its credit treatment and evidence, approved through the approval engine
(campus.curriculum.recognitions). Submitted records count in the completion check (campus.examinations.completion); one
credit satisfies one requirement only, so a student's course is recognised by one submitted record at most, and counts
once even when the student also passed it."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_platform.api import ApprovableDocument
from campus.curriculum import recognitions


class CreditRecognition(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		recognitions.check_recognition(self)

	def before_submit(self):
		super().before_submit()
		frappe.db.get_value(
			"Student", self.student, "name", for_update=True
		)  # one recognition per course at a time
		other = frappe.db.get_value(
			"Credit Recognition",
			{"student": self.student, "course": self.course, "docstatus": 1, "name": ["!=", self.name]},
			"name",
			for_update=True,
		)
		if other:
			frappe.throw(
				_("{0} is already recognised for {1} by {2}.").format(
					frappe.bold(self.course), self.student, other
				)
			)

	def before_cancel(self):
		recognitions.check_cancel(self)
