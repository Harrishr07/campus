"""M06-03 QP Setter Nomination: the setters and the scrutiniser of a course's paper, and the date it is due.
Confidential: Exam Confidential only (campus.examinations.question_papers)."""

import frappe
from frappe import _
from frappe.model.document import Document


class QPSetterNomination(Document):
	def validate(self):
		self.company = frappe.db.get_value("Exam Session", self.exam_session, "company")
		if self.scrutiniser and self.scrutiniser in {row.employee for row in self.setters}:
			frappe.throw(_("The scrutiniser cannot also set the paper."))
