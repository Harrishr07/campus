"""M06-08 CIA Schedule: the CIA of one course offering in its term: the template (from the offering's curriculum
regulation and course type), assessment dates, the question pattern (CO tag and Bloom level per question) and the
entry deadline, after which the offering's CIA marks lock (campus.examinations.cia).

The deadline is the COE's to set; the instructors of the offering may edit the question pattern until the lock."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_datetime

from campus.examinations import cia
from campus.examinations.access import MARKS_ROLES, has_any_role

DEADLINE_ROLES = (*MARKS_ROLES, "Dean Academics")


class CIASchedule(Document):
	def validate(self):
		self.validate_offering()
		self.template = cia.template_for(self.course_offering)
		self.check_deadline_owner()
		if not self.is_new() and cia.lock_state(self.name) == cia.LOCKED and self.pattern_changed():
			frappe.throw(_("The question pattern is locked with the CIA marks. An approved CIA Unlock Request reopens it."))
		self.check_pattern()

	def validate_offering(self):
		if frappe.db.get_value("Student Group", self.course_offering, "group_based_on") != "Course":
			frappe.throw(_("A CIA Schedule is for a course offering (a Student Group based on Course)."))
		if frappe.db.exists(cia.SCHEDULE, {"course_offering": self.course_offering, "name": ["!=", self.name]}):
			frappe.throw(_("{0} already has a CIA Schedule.").format(frappe.bold(self.course_offering)))

	def check_deadline_owner(self):
		before = None if self.is_new() else self.get_doc_before_save()
		moved = not before or get_datetime(before.entry_deadline) != get_datetime(self.entry_deadline)
		if moved and not has_any_role(frappe.session.user, DEADLINE_ROLES):
			frappe.throw(_("Only the COE sets the CIA entry deadline."), frappe.PermissionError)
		if moved:
			self.locked_on = None  # a moved deadline locks (and consolidates) again

	def pattern_changed(self):
		before = self.get_doc_before_save()
		return pattern(before) != pattern(self)

	def check_pattern(self):
		components = {row.component: row.max_marks for row in frappe.get_doc(cia.TEMPLATE, self.template).components}
		totals, seen = {}, set()
		for row in self.questions:
			if row.component not in components:
				frappe.throw(_("Question row {0}: {1} is not a component of {2}.").format(row.idx, row.component, self.template))
			if (row.component, row.question) in seen:
				frappe.throw(_("Question row {0}: {1} {2} is listed twice.").format(row.idx, row.component, row.question))
			if row.max_marks <= 0:
				frappe.throw(_("Question row {0}: the maximum must be above zero.").format(row.idx))
			seen.add((row.component, row.question))
			totals[row.component] = totals.get(row.component, 0) + row.max_marks
		for component, maximum in components.items():
			if flt(totals.get(component, 0), 6) != flt(maximum, 6):
				frappe.throw(
					_("The questions of {0} must add up to {1} marks (now {2}).").format(component, maximum, totals.get(component, 0))
				)
		for row in self.components:
			if row.component not in components:
				frappe.throw(_("Component row {0}: {1} is not a component of {2}.").format(row.idx, row.component, self.template))


def pattern(doc):
	return sorted((q.component, q.question, flt(q.max_marks), q.course_outcome, q.bloom_level) for q in doc.questions)
