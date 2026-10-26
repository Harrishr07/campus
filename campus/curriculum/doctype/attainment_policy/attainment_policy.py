"""M03-03 Attainment Policy: the active one of a regulation gives the direct / indirect weights of a CO, the CIA / ESE
split of the direct, the student threshold, the level bands, the survey rating scale, the CO and PO / PSO targets, and
the weight of the programme exit survey in a PO / PSO (campus.curriculum.attainment).

A run copies the values it used. Once a submitted run used a policy its values are locked: disable it and create a
new policy for the regulation (one active policy per regulation)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

PERCENT_FIELDS = (
	"direct_weight",
	"indirect_weight",
	"cia_weight",
	"ese_weight",
	"po_indirect_weight",
	"student_threshold",
)
RUNS = ("CO Attainment Run", "PO Attainment Run")


class AttainmentPolicy(Document):
	def validate(self):
		self.check_one_active()
		self.check_locked()
		for field in PERCENT_FIELDS:
			if not 0 <= flt(self.get(field)) <= 100:
				frappe.throw(_("{0} runs from 0 to 100.").format(_(self.meta.get_label(field))))
		if flt(self.student_threshold) <= 0:
			frappe.throw(_("Set a student threshold above 0."))
		if cint(self.survey_scale) < 2:
			frappe.throw(_("The survey rating scale is the highest rating, at least 2."))
		for first, second in (("direct_weight", "indirect_weight"), ("cia_weight", "ese_weight")):
			if abs(flt(self.get(first)) + flt(self.get(second)) - 100) >= 0.01:
				frappe.throw(
					_("{0} and {1} must add up to 100.").format(
						_(self.meta.get_label(first)), _(self.meta.get_label(second))
					)
				)
		self.validate_bands()

	def check_one_active(self):
		if self.disabled:
			return
		others = {
			"regulation": self.regulation,
			"disabled": 0,
			**({} if self.is_new() else {"name": ["!=", self.name]}),
		}
		other = frappe.db.get_value("Attainment Policy", others)
		if other:
			frappe.throw(
				_("Regulation {0} already has an active Attainment Policy: {1}.").format(
					frappe.bold(self.regulation), frappe.bold(other)
				)
			)

	def check_locked(self):
		"""A policy a submitted run used keeps its values; only Disabled may change."""
		before = None if self.is_new() else self.get_doc_before_save()
		if not before or values_of(before) == values_of(self):
			return
		used = next(
			filter(None, (frappe.db.get_value(d, {"policy": self.name, "docstatus": 1}) for d in RUNS)), None
		)
		if used:
			frappe.throw(
				_(
					"Submitted run {0} used this policy, so its values are locked. Disable it and create a new policy for {1}."
				).format(frappe.bold(used), frappe.bold(self.regulation))
			)

	def validate_bands(self):
		bands = sorted((cint(b.level), flt(b.min_students_percent)) for b in self.level_bands)
		levels = [level for level, _minimum in bands]
		if not bands or len(set(levels)) != len(levels) or levels[0] < 1:
			frappe.throw(_("Give each level (1, 2, 3 ...) one band."))
		minimums = [minimum for _level, minimum in bands]
		if any(not 0 < m <= 100 for m in minimums) or any(a >= b for a, b in zip(minimums, minimums[1:])):
			frappe.throw(
				_("Each band's minimum share of students runs from above 0 to 100 and rises with the level.")
			)
		for field in ("target_level", "po_target_level"):
			if flt(self.get(field)) > levels[-1]:
				frappe.throw(
					_("{0} cannot be above the top level {1}.").format(
						_(self.meta.get_label(field)), levels[-1]
					)
				)


def values_of(policy):
	fields = (*PERCENT_FIELDS, "survey_scale", "target_level", "po_target_level", "regulation")
	return (
		tuple(flt(policy.get(f)) if f != "regulation" else policy.get(f) for f in fields),
		tuple(sorted((cint(b.level), flt(b.min_students_percent)) for b in policy.level_bands)),
	)
