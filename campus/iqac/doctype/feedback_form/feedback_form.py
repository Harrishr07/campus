"""M01-05 Feedback Form: the questions of a survey (Likert 1-5, choice or text), each optionally tagged with a course
outcome (CO1, CO2, ...) so that its ratings give the indirect CO score of a course offering (M03-03)."""

import frappe
from frappe import _
from frappe.model.document import Document


class FeedbackForm(Document):
	def validate(self):
		for row in self.questions:
			row.course_outcome = (row.course_outcome or "").strip().upper() or None
			if row.question_type == "Choice" and len(choice_options(row)) < 2:
				frappe.throw(
					_("Row {0}: a choice question needs at least two options, one per line.").format(row.idx)
				)
			if row.course_outcome and row.question_type != "Likert":
				frappe.throw(
					_(
						"Row {0}: only a Likert question can carry a CO tag (its rating is the CO score)."
					).format(row.idx)
				)


def choice_options(row):
	return [line.strip() for line in (row.options or "").splitlines() if line.strip()]
