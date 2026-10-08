"""M06-04 Valuation Allocation: a bundle given to an examiner (internal or external) for one valuation round.

Rounds 1 and 2 take every script of the bundle. Round 3 is created by campus.examinations.valuation when two
valuations differ beyond the rule, holding only those scripts, Unassigned until the COE names an examiner.
One examiner values a bundle in one round only, and only a Complete bundle is allocated. A teacher of the course
in the session's term is refused unless every Exam Rule Set of the bundle's students allows it
(`allow_course_teacher_as_examiner`). Who reads it: campus.examinations.valuation_access.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from campus.examinations import valuation

THIRD = "3"


class ValuationAllocation(Document):
	def validate(self):
		bundle = frappe.db.get_value("Answer Script Bundle", self.bundle, ["exam_session", "course", "company", "status"], as_dict=True)
		if bundle.pop("status") != "Complete":
			frappe.throw(_("Only a Complete bundle can be allocated."))
		self.update(bundle)
		self.set_examiner()
		self.check_course_teacher()
		self.check_unique()
		self.set_scripts()
		self.check_frozen_after_valuation()
		self.status = self.computed_status()

	def set_examiner(self):
		if self.examiner:
			return
		if self.examiner_type == "Internal" and self.employee:
			self.examiner = frappe.db.get_value("Employee", self.employee, "user_id")
		elif self.examiner_type == "External" and self.external_member:
			email = frappe.db.get_value("External Member", self.external_member, "email")
			self.examiner = email and frappe.db.get_value("User", {"email": email})
		if not self.examiner and self.valuation_round != THIRD:
			frappe.throw(_("Choose the examiner's user, or an Employee / External Member that has one."))

	def check_course_teacher(self):
		if not self.examiner or self.examiner not in course_teachers(self.exam_session, self.course):
			return
		rule_sets = valuation.bundle_rule_sets(self.bundle)
		if not rule_sets or not all(cint(r.allow_course_teacher_as_examiner) for r in rule_sets):
			frappe.throw(_("{0} teaches {1} this term and cannot value its scripts.").format(self.examiner, self.course))

	def check_unique(self):
		others = frappe.get_all(
			self.doctype, {"bundle": self.bundle, "name": ["!=", self.name]}, ["valuation_round", "examiner"]
		)
		if any(o.valuation_round == self.valuation_round for o in others):
			frappe.throw(_("Round {0} of this bundle is already allocated.").format(self.valuation_round))
		for other in others:
			if self.examiner and other.examiner == self.examiner:
				frappe.throw(_("{0} already values this bundle in round {1}.").format(self.examiner, other.valuation_round))

	def set_scripts(self):
		if self.valuation_round == THIRD:
			if not self.flags.third_valuation and (self.is_new() or self.scripts_changed()):
				frappe.throw(_("Third valuations are allocated automatically, script by script."))
			return
		if self.is_new() or self.scripts_changed():
			numbers = frappe.get_all(
				"Answer Script Bundle Script", {"parent": self.bundle, "parenttype": "Answer Script Bundle"}, pluck="dummy_number", order_by="idx"
			)  # fmt: skip
			self.set("scripts", [{"dummy_number": n} for n in numbers])

	def scripts_changed(self):
		before = [] if self.is_new() else [s.dummy_number for s in self.get_doc_before_save().scripts]
		return [s.dummy_number for s in self.scripts] != before

	def check_frozen_after_valuation(self):
		if self.is_new() or not frappe.db.exists("Valuation Entry", {"allocation": self.name, "docstatus": ["<", 2]}):
			return
		before = self.get_doc_before_save()
		if any(self.get(f) != before.get(f) for f in ("bundle", "valuation_round", "examiner")):
			frappe.throw(_("The examiner, bundle and round are fixed once marks are entered."))

	def computed_status(self):
		if not self.examiner:
			return "Unassigned"
		valued = set(frappe.get_all("Valuation Entry", {"allocation": self.name, "docstatus": 1}, pluck="dummy_number"))
		return "Completed" if self.scripts and all(s.dummy_number in valued for s in self.scripts) else "Allocated"


def course_teachers(exam_session, course):
	"""Users of the instructors of any offering of `course` in the session's term."""
	term = frappe.db.get_value("Exam Session", exam_session, "academic_term")
	group, teacher = frappe.qb.DocType("Student Group"), frappe.qb.DocType("Student Group Instructor")
	instructor, employee = frappe.qb.DocType("Instructor"), frappe.qb.DocType("Employee")
	return set(
		frappe.qb.from_(teacher)
		.join(group).on(group.name == teacher.parent)
		.join(instructor).on(instructor.name == teacher.instructor)
		.join(employee).on(employee.name == instructor.employee)
		.select(employee.user_id)
		.where(
			(teacher.parenttype == "Student Group") & (group.course == course) & (group.academic_term == term)
			& (group.group_based_on == "Course") & employee.user_id.isnotnull()
		)
		.run(pluck=True)
	)  # fmt: skip
