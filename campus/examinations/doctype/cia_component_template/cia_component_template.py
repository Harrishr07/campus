"""M06-08 CIA Component Template: how a regulation converts the CIA of one course type, e.g. R2022 theory:
two assessments of 100 (40 assignment + 60 test) to 40. The weights plus the attendance maximum equal the
converted CIA maximum, which must match the course type's CIA maximum in the regulation's Exam Rule Set.
Locked with its regulation like the other rule records (rule_lock)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from campus.examinations.rule_lock import validate_rule_delete, validate_rule_lock


class CIAComponentTemplate(Document):
	def validate(self):
		validate_rule_lock(self)
		self.check_unique()
		self.check_components()
		self.check_rule_set_maximum()

	def on_trash(self):
		validate_rule_delete(self)

	def check_unique(self):
		if frappe.db.exists(
			"CIA Component Template",
			{"regulation": self.regulation, "course_type": self.course_type, "name": ["!=", self.name]},
		):
			frappe.throw(
				_("A CIA Component Template for {0} {1} exists already.").format(
					self.regulation, _(self.course_type)
				)
			)

	def check_components(self):
		names = [row.component for row in self.components]
		if len(names) != len(set(names)):
			frappe.throw(_("Component names must be unique."))
		for row in self.components:
			if row.max_marks <= 0 or row.weight <= 0:
				frappe.throw(
					_("Row {0}: the entered-out-of marks and the weight must be above zero.").format(row.idx)
				)
		if not self.includes_attendance_marks:
			self.attendance_max = 0
		total = flt(sum(row.weight for row in self.components) + flt(self.attendance_max), 6)
		if total != flt(self.cia_max, 6):
			frappe.throw(
				_(
					"The weights ({0}) plus the attendance maximum must equal the converted CIA maximum {1}."
				).format(total, self.cia_max)
			)

	def check_rule_set_maximum(self):
		rule_set = frappe.db.get_value("Exam Rule Set", {"regulation": self.regulation})
		maximum = rule_set and frappe.db.get_value(
			"Exam Rule Set Type",
			{"parent": rule_set, "parenttype": "Exam Rule Set", "course_type": self.course_type},
			"cia_max",
		)
		if maximum and flt(maximum) != flt(self.cia_max):
			frappe.throw(
				_(
					"The converted CIA maximum must be {0}, the {1} CIA maximum of the regulation's Exam Rule Set."
				).format(maximum, _(self.course_type))
			)
