"""M05-05 Scholarship Application: a student's claim on a scheme for an academic year, sanctioned by submitting.

New applications check the scheme's eligibility rule; a renewal also needs the earlier sanctioned application and is
blocked, with every reason listed, while the student has more arrears than the scheme allows or attendance below its
bar (campus.campus_finance.scholarships.renewal_check). The sanctioned amount defaults to the scheme's amount rule
and may only be lowered. Sanction goes through the approval engine. The doctype is on the Campus Settings mandatory
approval list by default, so without a matching Approval Policy the sanction is refused; a college that takes it off the
list lets the submitter sanction alone (no separation of duties) when no policy matches.
Disbursements are rows linking Payment Entries or Journal Entries (campus.campus_finance.scholarships.disburse).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission
from frappe.utils import flt

from campus.campus_finance import scholarships
from campus.campus_platform.api import ApprovableDocument

RENEWAL = "Renewal"


class ScholarshipApplication(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		if self.docstatus == 0:
			self.set_context()
			self.check_duplicate()
			self.check_rules()
			self.set_amount()

	def before_submit(self):
		super().before_submit()
		self.check_rules()  # facts may have changed since the draft was saved
		if flt(self.sanctioned_amount) <= 0:
			frappe.throw(_("Nothing to sanction: the sanctioned amount is zero."))
		self.status = "Sanctioned"

	def before_cancel(self):
		if scholarships.disbursed_total(self.name):
			frappe.throw(_("Cancel the disbursement vouchers of {0} first.").format(self.name))

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def set_context(self):
		student = frappe.get_doc("Student", self.student)
		scheme = frappe.db.get_value("Scholarship Scheme", self.scheme, ["company", "scheme_type"], as_dict=True)
		if not has_user_permission(student):  # Company User Permissions
			frappe.throw(_("You are not permitted to apply for {0}.").format(frappe.bold(self.student)), frappe.PermissionError)
		if scheme.company != student.oc_company:
			frappe.throw(_("Scheme {0} belongs to {1}, not to the student's company.").format(self.scheme, scheme.company))
		self.company, self.scheme_type = scheme.company, scheme.scheme_type

	def check_duplicate(self):
		"""One live application per student, scheme and year; the student's row lock serialises concurrent saves."""
		frappe.db.get_value("Student", self.student, "name", for_update=True)
		clash = frappe.db.get_value(
			"Scholarship Application",
			{"student": self.student, "scheme": self.scheme, "academic_year": self.academic_year, "docstatus": ["<", 2], "name": ["!=", self.name or ""]},
			"name", for_update=True,
		)  # fmt: skip
		if clash:
			frappe.throw(_("{0} already covers this student, scheme and year.").format(clash))

	def check_rules(self):
		scheme = frappe.get_doc("Scholarship Scheme", self.scheme)
		reasons = scholarships.eligibility_reasons(
			scheme.enabled, scheme.eligible_student_category, self.student_category()
		)
		if self.application_type == RENEWAL:
			reasons += self.renewal_reasons(scheme)
		if reasons:
			frappe.throw("<br>".join(reasons), title=_("Not Eligible"))

	def student_category(self):
		"""The category on the student's latest submitted enrolment (Student itself carries none)."""
		return frappe.db.get_value(
			"Program Enrollment", {"student": self.student, "docstatus": 1}, "student_category", order_by="creation desc"
		)

	def renewal_reasons(self, scheme):
		if not scheme.renewable:
			return [_("The scheme cannot be renewed.")]
		previous = self.previous_application and frappe.db.get_value(
			"Scholarship Application", self.previous_application, ["student", "scheme", "docstatus", "academic_year"], as_dict=True
		)
		if not previous or previous.docstatus != 1 or (previous.student, previous.scheme) != (self.student, self.scheme):
			return [_("A renewal needs the student's sanctioned application of the same scheme.")]
		if not self.is_earlier_year(previous.academic_year):
			return [_("The renewed application must be of an earlier academic year.")]
		return scholarships.renewal_check(self.student, scheme)

	def is_earlier_year(self, academic_year):
		start = frappe.db.get_value("Academic Year", academic_year, "year_start_date")
		return bool(start) and start < frappe.db.get_value("Academic Year", self.academic_year, "year_start_date")

	def set_amount(self):
		scheme = frappe.get_doc("Scholarship Scheme", self.scheme)
		most = scholarships.scheme_amount(scheme.amount_type, scheme.amount, scheme.percent, scheme.max_amount, self.base_fee)
		if not flt(self.sanctioned_amount):
			self.sanctioned_amount = most
		elif flt(self.sanctioned_amount) > most:
			frappe.throw(_("The sanctioned amount cannot exceed {0}, what the scheme allows.").format(most))
