"""M06-06 Revaluation Application: a student's Photocopy, Revaluation or Review of courses of a published Student
Result, inside the window from publication, with its fee (rules: campus.examinations.revaluation)."""

from frappe.model.document import Document

from campus.examinations import revaluation


class RevaluationApplication(Document):
	def validate(self):
		revaluation.validate_application(self)

	def before_submit(self):
		revaluation.check_invoiceable(self)

	def on_submit(self):
		revaluation.queue_fee(self)

	def before_cancel(self):
		revaluation.check_cancel(self)

	def on_cancel(self):
		revaluation.cancel_fee(self)
