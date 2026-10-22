"""M04-10 Late Joining Request: approval for an admitted student to join after their reporting deadline.

The admission office raises it for an Admitted student with the effective joining date and a reason; it runs
through the approval engine (seeded policy: Principal approval) and with no policy it is never submitted (fail
closed). The approved (submitted) request lets the joining confirmation use that date (campus.admissions.reporting).
One live request per applicant; cancelling an approved one withdraws the approval.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from campus.admissions.admit import check_company_access
from campus.admissions.reporting import LATE_REQUEST, student_deadline
from campus.campus_platform.api import ApprovableDocument, find_policy
from campus.student_services.api import ADMITTED


class LateJoiningRequest(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		student = self.set_context()
		self.check_late()
		if student.oc_academic_status != ADMITTED:
			frappe.throw(_("{0} is {1}: only an admitted student who has not joined needs a late joining approval.").format(
				frappe.bold(student.name), _(student.oc_academic_status)
			))  # fmt: skip
		others = self.other_requests()
		if others:
			frappe.throw(_("{0} already has a Late Joining Request: {1}.").format(self.applicant, others[0]))

	def before_submit(self):
		super().before_submit()
		if not find_policy(self):
			frappe.throw(_("No Approval Policy is set for {0}; it cannot be submitted without approval.").format(_(self.doctype)))

	def set_context(self):
		student = frappe.db.get_value(
			"Student", {"student_applicant": self.applicant}, ["name", "student_name", "oc_company", "oc_academic_status", "oc_reporting_deadline"],
			as_dict=True,
		)  # fmt: skip
		if not student:
			frappe.throw(_("Applicant {0} is not admitted yet.").format(self.applicant))
		check_company_access(student.oc_company)
		self.program = frappe.db.get_value("Student Applicant", self.applicant, "program")
		self.student, self.student_name, self.company = student.name, student.student_name, student.oc_company
		self.reporting_deadline = student_deadline(student.oc_reporting_deadline, self.program)
		return student

	def check_late(self):
		if not self.reporting_deadline:
			frappe.throw(_("{0} has no reporting deadline: they may join on any date.").format(frappe.bold(self.student)))
		if getdate(self.joining_date) <= getdate(self.reporting_deadline):
			frappe.throw(
				_("The joining date {0} is not after the reporting deadline {1}: no approval is needed.").format(
					frappe.format(self.joining_date, "Date"), frappe.format(self.reporting_deadline, "Date")
				)
			)

	def other_requests(self):
		return frappe.get_all(
			LATE_REQUEST, {"applicant": self.applicant, "docstatus": ("<", 2), "name": ("!=", self.name)}, pluck="name"
		)
