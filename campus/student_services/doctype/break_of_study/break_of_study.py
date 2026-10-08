"""M05-03 Break of Study: an authorised break in a student's programme.

All of the student's approved breaks together may last at most the Exam Rule Set's maximum years, plus its
exceptional years when this break is marked exceptional (with a reason). A student already on a break cannot
start another. Approval runs through the approval engine (seeded policy: HOD recommendation, then Principal
approval); final approval submits it and sets the student's academic status to Break of Study. Cancelling sets
it back to Active. The student returns through a Rejoin Application.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission
from frappe.utils import cint, getdate

from campus.campus_platform.api import ApprovableDocument, latest_enrollment
from campus.student_services import student_records, withdrawal_rules

DOCTYPE = "Break of Study"
ON_BREAK, ACTIVE = "Break of Study", "Active"


class BreakofStudy(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.set_context()
		if self.exceptional and not (self.exceptional_reason or "").strip():
			frappe.throw(_("Give the reason for the exceptional break."))
		if not self.exceptional:
			self.exceptional_reason = None
		self.check_limit(self.used_days())

	def before_submit(self):
		super().before_submit()
		frappe.db.get_value("Student", self.student, "name", for_update=True)  # one break submit at a time per student
		self.check_limit(self.used_days(lock=True))
		if frappe.db.get_value("Student", self.student, "oc_academic_status", for_update=True) == ON_BREAK:
			self.throw_on_break()

	def on_submit(self):
		frappe.db.set_value("Student", self.student, "oc_academic_status", ON_BREAK)

	def on_cancel(self):
		if frappe.db.get_value("Student", self.student, "oc_academic_status") == ON_BREAK:
			frappe.db.set_value("Student", self.student, "oc_academic_status", ACTIVE)

	def set_context(self):
		student = frappe.get_doc("Student", self.student)
		if not has_user_permission(student):  # Company User Permissions
			frappe.throw(_("You are not permitted to act for {0}.").format(frappe.bold(self.student)), frappe.PermissionError)
		if self.docstatus == 0 and student.oc_academic_status == ON_BREAK:
			self.throw_on_break()
		self.company = student.oc_company
		self.program = (latest_enrollment(self.student) or {}).get("program")
		self.department = student_records.student_department(self.program)
		self.break_days = withdrawal_rules.break_days(getdate(self.from_date), getdate(self.to_date))

	def check_limit(self, used_days):
		rule = student_records.rule_values(self.student)
		refusal = withdrawal_rules.break_refusal(
			used_days, self.break_days, rule.break_max_years, rule.break_exceptional_years, cint(self.exceptional)
		)
		if refusal == withdrawal_rules.BAD_DATES:
			frappe.throw(_("A break of study cannot end before it starts."))
		if refusal:
			years = rule.break_max_years + (rule.break_exceptional_years if self.exceptional else 0)
			frappe.throw(
				_("The breaks of study of {0} may total at most {1} year(s); with this one they come to {2} days.").format(
					frappe.bold(self.student), years, used_days + self.break_days
				)
			)

	def used_days(self, lock=False):
		"""Days of the student's other approved breaks (a locking read when `lock`)."""
		other = frappe.qb.DocType(DOCTYPE)
		query = (
			frappe.qb.from_(other)
			.select(other.break_days)
			.where((other.student == self.student) & (other.docstatus == 1) & (other.name != (self.name or "")))
		)
		return sum(cint(days) for days in (query.for_update() if lock else query).run(pluck=True))

	def throw_on_break(self):
		frappe.throw(_("{0} is already on a break of study; record the rejoin first.").format(frappe.bold(self.student)))
