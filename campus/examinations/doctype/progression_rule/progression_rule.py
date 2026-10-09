"""M05-03 Progression Rule: the term-end progression of a regulation's students (campus.examinations.progression):
detained above an arrear limit (year back), promoted on probation below a CGPA, else promoted. Locked with its
regulation like the other rule records (campus.examinations.rule_lock)."""

from frappe.model.document import Document

from campus.examinations.rule_lock import validate_rule_delete, validate_rule_lock


class ProgressionRule(Document):
	def validate(self):
		validate_rule_lock(self)

	def on_trash(self):
		validate_rule_delete(self)
