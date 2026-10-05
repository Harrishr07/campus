"""M05-02 Attendance Rule: the eligibility thresholds of a regulation (formula, overall, medical band, per course).

One record per Regulation, so `get_rule(student, "Attendance Rule")` resolves it.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class AttendanceRule(Document):
	def validate(self):
		overall, band, per_course = (flt(self.overall_min_pct), flt(self.medical_band_min_pct), flt(self.per_course_min_pct))
		if not (0 <= band <= overall <= 100):
			frappe.throw(_("The medical band minimum must not exceed the overall minimum, and both lie within 0-100."))
		if not 0 <= per_course <= 100:
			frappe.throw(_("The per-course minimum must lie within 0-100."))
