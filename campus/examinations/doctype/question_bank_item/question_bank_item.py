"""M06-03 Question Bank Item: a question of a course tagged with its CO, Bloom level, marks and difficulty.
Readable by Exam Confidential only (campus.examinations.question_papers).

Server-owned audit fields: `editors` (every user who wrote the question, its tags or marks; they never approve a
paper using it) and `retired_by_withdrawal` (set when a sealed paper using it is withdrawn: the item stays disabled
and never goes on another paper)."""

import frappe
from frappe import _
from frappe.model.document import Document

CONTENT_FIELDS = ("course", "course_outcome", "bloom_level", "marks", "question")


class QuestionBankItem(Document):
	def validate(self):
		before = self.get_doc_before_save()
		self.retired_by_withdrawal = before.retired_by_withdrawal if before else None
		if self.retired_by_withdrawal and not self.disabled:
			frappe.throw(
				_("{0} was on withdrawn paper {1}; it stays retired.").format(
					self.name, self.retired_by_withdrawal
				)
			)
		editors = (before.editors or "").split() if before else []
		changed = not before or any(before.get(f) != self.get(f) for f in CONTENT_FIELDS)
		if changed and frappe.session.user not in editors:
			editors.append(frappe.session.user)
		self.editors = "\n".join(editors) or None
