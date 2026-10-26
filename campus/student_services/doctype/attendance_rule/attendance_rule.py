"""M05-02 Attendance Rule: the eligibility thresholds of a regulation (formula, overall, medical band, per course),
whether On Duty and medical leave count, the condonation fee and the CIA attendance-mark bands.

One record per Regulation, so `get_rule(student, "Attendance Rule")` resolves it.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class AttendanceRule(Document):
	def validate(self):
		overall, band, per_course = (
			flt(self.overall_min_pct),
			flt(self.medical_band_min_pct),
			flt(self.per_course_min_pct),
		)
		if not (0 <= band <= overall <= 100):
			frappe.throw(
				_("The medical band minimum must not exceed the overall minimum, and both lie within 0-100.")
			)
		if not 0 <= per_course <= 100:
			frappe.throw(_("The per-course minimum must lie within 0-100."))
		if flt(self.condonation_fee) < 0:
			frappe.throw(_("The condonation fee cannot be negative."))
		self.validate_mark_bands()

	def validate_mark_bands(self):
		"""Each band needs a valid range and marks; bands must not overlap (so a percentage has one band)."""
		bands = sorted(self.mark_bands, key=lambda b: b.from_pct)
		for band in bands:
			if not 0 <= band.from_pct <= 100 or (
				band.to_pct is not None and band.to_pct != "" and not band.from_pct <= band.to_pct <= 100
			):
				frappe.throw(_("Row {0}: the percentage range is not valid.").format(band.idx))
			if flt(band.marks) < 0:
				frappe.throw(_("Row {0}: marks cannot be negative.").format(band.idx))
		for before, after in zip(bands, bands[1:]):
			if not before.to_pct or before.to_pct >= after.from_pct:
				frappe.throw(_("Row {0}: the percentage range overlaps another band.").format(after.idx))
