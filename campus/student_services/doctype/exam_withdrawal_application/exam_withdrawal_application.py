"""M06-01 Exam Withdrawal Application: a student withdraws from the examination of one or more registered courses.

Only a course of the session's term (kind Current or Dropped) is withdrawn; an arrear or bridge course is not
(thin cut, fix round 1 ruling). Rules (withdrawal_rules, values from the regulation's records):
- once in the programme: a second approved withdrawal of the same programme is refused, nothing lifts this;
- within the Exam Rule Set's window of days after the exam of each course; only the Principal's special case
  (with a reason, set by the PRINCIPAL position holder of the college) lifts the window.
The window is checked when approval is requested and again on submit, so a late draft can wait for the
Principal's special case. Approval runs through the approval engine (seeded policy: HOD recommendation, then
Principal approval; the requester and owner never approve). Final approval submits it; the Result Run then gives
the courses the regulation's withdrawal code (WD in R2022, WC in R2026, result WD), which is not an attempt and
not an appearance for distinction (examinations.rules). An existing unpublished Student Result is recomputed
on submit and on cancel.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission
from frappe.utils import cint, getdate, today

from campus.campus_platform.api import ApprovableDocument, latest_enrollment
from campus.student_services import student_records, withdrawal_rules

DOCTYPE = "Exam Withdrawal Application"


class ExamWithdrawalApplication(ApprovableDocument, Document):
	def before_insert(self):
		self.application_date = today()

	def validate(self):
		super().validate()
		self.keep_application_date()
		self.set_context()
		self.check_session_open()
		self.set_courses()
		self.check_special_case()
		if self.earlier_withdrawals():
			self.throw_refusal(withdrawal_rules.REPEAT)

	def before_approval_request(self):
		self.check_rules()

	def before_submit(self):
		super().before_submit()
		student_records.require_policy(self)
		self.check_rules()

	def on_submit(self):
		student_records.refresh_result(self.student, self.exam_session)

	def before_cancel(self):
		self.check_session_open()

	def on_cancel(self):
		student_records.refresh_result(self.student, self.exam_session)

	def keep_application_date(self):
		before = self.get_doc_before_save()
		if before:
			self.application_date = before.application_date

	def set_context(self):
		student = frappe.get_doc("Student", self.student)
		if not has_user_permission(student):  # Company User Permissions
			frappe.throw(_("You are not permitted to act for {0}.").format(frappe.bold(self.student)), frappe.PermissionError)
		self.company = student.oc_company
		registration = frappe.db.get_value(
			"Exam Registration", {"exam_session": self.exam_session, "student": self.student}, ["name", "program"], as_dict=True
		)
		if not registration:
			frappe.throw(_("{0} is not registered for {1}.").format(frappe.bold(self.student), frappe.bold(self.exam_session)))
		self.registration = registration.name
		self.program, self.department = student_records.programme_and_department(
			self.student, registration.program or (latest_enrollment(self.student) or {}).get("program")
		)
		self.window_days = student_records.rule_values(self.student).withdrawal_days
		self.withdrawal_code = student_records.regulation_withdrawal_code(self.student)

	def check_session_open(self):
		if frappe.db.get_value("Exam Session", self.exam_session, "status") == "Published":
			frappe.throw(_("The results of {0} are published; a withdrawal can no longer change them.").format(frappe.bold(self.exam_session)))

	def set_courses(self):
		from campus.examinations.api import TERM_KINDS

		registered = {
			row.course: row
			for row in frappe.get_all(
				"Exam Registration Course",
				{"parent": self.registration, "parenttype": "Exam Registration"},
				["course", "kind", "eligibility"],
			)
		}
		seen = set()
		for row in self.courses:
			if row.course in seen:
				frappe.throw(_("Row {0}: {1} is listed twice.").format(row.idx, frappe.bold(row.course)))
			seen.add(row.course)
			course = registered.get(row.course)
			if not course or course.eligibility != "Eligible":
				frappe.throw(_("Row {0}: {1} is not registered (and eligible) in this session.").format(row.idx, frappe.bold(row.course)))
			if course.kind not in TERM_KINDS:
				frappe.throw(
					_("Row {0}: {1} is not a course of the term ({2}); only those can be withdrawn.").format(
						row.idx, frappe.bold(row.course), _(course.kind)
					)
				)
			row.exam_date = frappe.db.get_value(
				"Exam Schedule", {"parent": self.exam_session, "parenttype": "Exam Session", "course": row.course}, "exam_date"
			)
			if not row.exam_date:
				frappe.throw(_("Row {0}: the exam of {1} is not scheduled in this session.").format(row.idx, frappe.bold(row.course)))

	def check_special_case(self):
		"""Only the Principal sets, changes or clears the special case, and gives a reason for it."""
		before = self.get_doc_before_save()
		old = (cint(before.special_case), (before.special_case_reason or "").strip()) if before else (0, "")
		new = (cint(self.special_case), (self.special_case_reason or "").strip()) if self.special_case else (0, "")
		if new == old:
			self.special_case_by = before.special_case_by if before and self.special_case else None
			return
		if not student_records.is_principal(self.company):
			frappe.throw(_("Only the Principal may grant the special case."), frappe.PermissionError)
		if self.special_case and not new[1]:
			frappe.throw(_("Give the reason for the special case."))
		self.special_case_by = frappe.session.user if self.special_case else None

	def check_rules(self):
		"""Both rules against locked facts: one approval or submit at a time per student."""
		frappe.db.get_value("Student", self.student, "name", for_update=True)
		days = max(
			withdrawal_rules.days_after_exam(getdate(row.exam_date), getdate(self.application_date)) for row in self.courses
		)
		refusal = withdrawal_rules.withdrawal_refusal(
			self.earlier_withdrawals(lock=True), days, cint(self.window_days), cint(self.special_case)
		)
		if refusal:
			self.throw_refusal(refusal, days)

	def earlier_withdrawals(self, lock=False):
		"""Other approved withdrawals of the student in the programme (a locking read when `lock`)."""
		app = frappe.qb.DocType(DOCTYPE)
		query = (
			frappe.qb.from_(app)
			.select(app.name)
			.where((app.student == self.student) & (app.program == self.program) & (app.docstatus == 1))
			.where(app.name != (self.name or ""))
		)
		return len((query.for_update() if lock else query).run())

	def throw_refusal(self, refusal, days=None):
		if refusal == withdrawal_rules.REPEAT:
			frappe.throw(
				_("{0} has already withdrawn from an examination of {1}; a withdrawal is allowed only once in the programme.").format(
					frappe.bold(self.student), frappe.bold(self.program)
				)
			)
		frappe.throw(
			_("A withdrawal must be made within {0} days of the exam; {1} days have passed. Only the Principal's special case allows a later one.").format(
				cint(self.window_days), days
			)
		)
