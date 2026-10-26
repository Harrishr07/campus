"""M05-03 Break of Study: an authorised break in a student's programme.

All of the student's approved breaks together may last at most the Exam Rule Set's maximum years, plus its
exceptional years when this break is marked exceptional (with a reason). Breaks never overlap, and a student
already on a break cannot start another. Approval runs through the approval engine (seeded policy: HOD
recommendation, then Principal approval); with no policy the break is never submitted (fail closed). Final
approval submits it, keeps the student's lifecycle status in `previous_status` and moves the student to On Break
from the break's start (campus.student_services.lifecycle, M05-09); exam registration and the Result Run then skip
the student. Cancelling reverses that transition while it is still the student's latest; the student's Rejoin
Application restores the previous status.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission
from frappe.utils import cint, getdate

from campus.campus_platform.api import ApprovableDocument, latest_enrollment
from campus.student_services import lifecycle, lifecycle_rules, student_records, withdrawal_rules

DOCTYPE = "Break of Study"
ON_BREAK, ACTIVE = student_records.ON_BREAK, "Active"


class BreakofStudy(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.set_context()
		if self.exceptional and not (self.exceptional_reason or "").strip():
			frappe.throw(_("Give the reason for the exceptional break."))
		if not self.exceptional:
			self.exceptional_reason = None
		self.check_others(self.other_breaks())

	def before_submit(self):
		super().before_submit()
		student_records.require_policy(self)
		status = frappe.db.get_value(
			"Student", self.student, "oc_academic_status", for_update=True
		)  # one at a time
		if status == ON_BREAK:
			self.throw_on_break()
		self.check_others(self.other_breaks(lock=True))
		self.previous_status = status or ACTIVE

	def on_submit(self):
		lifecycle.transition(self.student, ON_BREAK, self.from_date, self.reason, self)

	def on_cancel(self):
		# a break migrated from before L-01 is undone to its previous status mapped onto the lifecycle statuses
		previous = lifecycle_rules.migrated_status(self.previous_status)
		lifecycle.revert(self, _("Break of Study {0} cancelled").format(self.name), legacy_status=previous)

	def set_context(self):
		student = frappe.get_doc("Student", self.student)
		if not has_user_permission(student):  # Company User Permissions
			frappe.throw(
				_("You are not permitted to act for {0}.").format(frappe.bold(self.student)),
				frappe.PermissionError,
			)
		if self.docstatus == 0 and student.oc_academic_status == ON_BREAK:
			self.throw_on_break()
		self.company = student.oc_company
		self.program, self.department = student_records.programme_and_department(
			self.student, (latest_enrollment(self.student) or {}).get("program")
		)
		self.break_days = withdrawal_rules.break_days(getdate(self.from_date), getdate(self.to_date))

	def check_others(self, others):
		for other in others:
			if withdrawal_rules.ranges_overlap(
				getdate(self.from_date), getdate(self.to_date), other.from_date, other.to_date
			):
				frappe.throw(_("This break overlaps the approved break {0}.").format(frappe.bold(other.name)))
		self.check_limit(sum(cint(other.break_days) for other in others))

	def check_limit(self, used_days):
		rule = student_records.rule_values(self.student)
		refusal = withdrawal_rules.break_refusal(
			used_days,
			self.break_days,
			rule.break_max_years,
			rule.break_exceptional_years,
			cint(self.exceptional),
		)
		if refusal == withdrawal_rules.BAD_DATES:
			frappe.throw(_("A break of study cannot end before it starts."))
		if refusal:
			years = rule.break_max_years + (rule.break_exceptional_years if self.exceptional else 0)
			frappe.throw(
				_(
					"The breaks of study of {0} may total at most {1} year(s); with this one they come to {2} days."
				).format(frappe.bold(self.student), years, used_days + self.break_days)
			)

	def other_breaks(self, lock=False):
		"""The student's other approved breaks (a locking read when `lock`)."""
		other = frappe.qb.DocType(DOCTYPE)
		query = (
			frappe.qb.from_(other)
			.select(other.name, other.from_date, other.to_date, other.break_days)
			.where(
				(other.student == self.student) & (other.docstatus == 1) & (other.name != (self.name or ""))
			)
		)
		return (query.for_update() if lock else query).run(as_dict=True)

	def throw_on_break(self):
		frappe.throw(
			_("{0} is already on a break of study; record the rejoin first.").format(
				frappe.bold(self.student)
			)
		)
