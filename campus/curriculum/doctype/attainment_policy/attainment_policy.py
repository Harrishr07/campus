"""M03-03 Attainment Policy: one per regulation. Direct / indirect weights of a CO, the CIA / ESE split of the direct,
the student threshold, the level bands, the CO and PO / PSO targets, and the weight of the programme exit survey in a
PO / PSO (campus.curriculum.attainment). A run copies the values it used, so editing a policy changes only the runs
computed afterwards, and only for its own regulation."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

PERCENT_FIELDS = ("direct_weight", "indirect_weight", "cia_weight", "ese_weight", "po_indirect_weight", "student_threshold")


class AttainmentPolicy(Document):
	def validate(self):
		others = {"regulation": self.regulation, **({} if self.is_new() else {"name": ["!=", self.name]})}
		if frappe.db.exists("Attainment Policy", others):
			frappe.throw(_("Regulation {0} already has an Attainment Policy.").format(frappe.bold(self.regulation)))
		for field in PERCENT_FIELDS:
			if not 0 <= flt(self.get(field)) <= 100:
				frappe.throw(_("{0} runs from 0 to 100.").format(_(self.meta.get_label(field))))
		if flt(self.student_threshold) <= 0:
			frappe.throw(_("Set a student threshold above 0."))
		for first, second in (("direct_weight", "indirect_weight"), ("cia_weight", "ese_weight")):
			if flt(self.get(first)) + flt(self.get(second)) != 100:
				frappe.throw(
					_("{0} and {1} must add up to 100.").format(_(self.meta.get_label(first)), _(self.meta.get_label(second)))
				)
		self.validate_bands()

	def validate_bands(self):
		bands = sorted((cint(b.level), flt(b.min_students_percent)) for b in self.level_bands)
		levels = [level for level, _minimum in bands]
		if not bands or len(set(levels)) != len(levels) or levels[0] < 1:
			frappe.throw(_("Give each level (1, 2, 3 ...) one band."))
		minimums = [minimum for _level, minimum in bands]
		if any(not 0 < m <= 100 for m in minimums) or any(a >= b for a, b in zip(minimums, minimums[1:])):
			frappe.throw(_("Each band's minimum share of students runs from above 0 to 100 and rises with the level."))
		for field in ("target_level", "po_target_level"):
			if flt(self.get(field)) > levels[-1]:
				frappe.throw(_("{0} cannot be above the top level {1}.").format(_(self.meta.get_label(field)), levels[-1]))
