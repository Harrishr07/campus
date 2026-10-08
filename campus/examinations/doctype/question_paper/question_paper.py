"""M06-03 Question Paper: the pattern (blueprint), sets A/B of bank questions, moderation and the encrypted PDFs.

Access, the release window and the access log live in campus.examinations.question_papers. Approving runs the
blueprint check (CO coverage, Bloom distribution: question_paper_rules) and seals the paper: a sealed paper cannot
be changed. Release At defaults to the slot start of the course in the session's schedule.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.examinations.question_paper_files import seal_attachments
from campus.examinations.question_paper_rules import blueprint_issues
from campus.examinations.question_papers import SEALED, slot_start


class QuestionPaper(Document):
	def validate(self):
		self.refuse_change_once_sealed()
		self.company = frappe.db.get_value("Exam Session", self.exam_session, "company")
		self.release_at = self.release_at or slot_start(self.exam_session, self.course)
		self.validate_questions()
		self.blueprint_issues = "\n".join(self.check_blueprint()) or None
		if self.moderation_status == SEALED:
			self.validate_approval()
		seal_attachments(self)

	def refuse_change_once_sealed(self):
		before = self.get_doc_before_save()
		if before and before.moderation_status == SEALED:
			frappe.throw(_("Question Paper {0} is approved and sealed; it cannot be changed.").format(self.name))

	def validate_questions(self):
		for row in self.questions:
			course, company = frappe.db.get_value("Question Bank Item", row.question_item, ["course", "company"])
			if course != self.course or company != self.company:
				frappe.throw(_("Row {0}: {1} is not a question of {2} in {3}.").format(row.idx, row.question_item, self.course, self.company))

	def check_blueprint(self):
		questions = [{"paper_set": q.paper_set, "course_outcome": q.course_outcome, "bloom_level": q.bloom_level,
			"marks": q.marks} for q in self.questions]  # fmt: skip
		return blueprint_issues(questions, [r.as_dict() for r in self.blueprint], self.total_marks)

	def validate_approval(self):
		if not self.release_at:
			frappe.throw(_("Set Release At before approving the paper."))
		if not self.set_a_file:
			frappe.throw(_("Attach the Set A paper before approving."))
		if self.blueprint_issues:
			frappe.throw(_("The paper does not match its blueprint:") + "<br>" + self.blueprint_issues.replace("\n", "<br>"))
