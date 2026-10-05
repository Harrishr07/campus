"""M12-02 Exam Rule Set: CIA/ESE maxima and pass thresholds per course type, for a regulation."""

import frappe
from frappe import _
from frappe.model.document import Document


class ExamRuleSet(Document):
	def validate(self):
		types = [row.course_type for row in self.types]
		if len(types) != len(set(types)):
			frappe.throw(_("Each course type may appear once."))
		for row in self.types:
			if row.cia_max < 0 or row.ese_max <= 0:
				frappe.throw(_("Row {0}: ESE maximum must be positive and CIA maximum not negative.").format(row.idx))
			if not (0 <= row.ese_min_pct <= 100 and 0 <= row.total_min_pct <= 100):
				frappe.throw(_("Row {0}: percentages lie within 0-100.").format(row.idx))
