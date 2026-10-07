"""M05-02 Condonation Request: a student in the medical band asks to be allowed to appear in a term.

Allowed only while the student's attendance for the term is in the regulation's medical band (below it the
student is Detained (SA) with no condonation option; above it none is needed). Approval runs through the
generic approval engine; on final approval the request is submitted, which makes `eligibility_status`
report the student Eligible for the term, and raises the regulation's condonation fee under the
"Condonation" fee category when it is above zero.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission

from campus.campus_finance.api import raise_fee_invoice
from campus.campus_platform.api import ApprovableDocument
from campus.student_services.api import rule_values, summarise, term_window
from campus.student_services.attendance_rules import MEDICAL_BAND, SHORTAGE

FEE_HEAD = "Condonation"


class CondonationRequest(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.set_company()
		self.check_duplicate()
		self.check_band()

	def on_submit(self):
		if self.fee_amount:
			invoice = raise_fee_invoice(
				self.student, FEE_HEAD, self.fee_amount, self.company,
				_("Condonation of attendance shortage, {0}").format(self.academic_term),
			)  # fmt: skip
			self.db_set("fee_invoice", invoice.name)

	def before_cancel(self):
		if self.fee_invoice and frappe.db.get_value("Sales Invoice", self.fee_invoice, "docstatus") == 1:
			frappe.throw(_("Cancel or credit the fee invoice {0} before cancelling this condonation.").format(self.fee_invoice))

	def set_company(self):
		student = frappe.get_doc("Student", self.student)
		if not has_user_permission(student):  # Company User Permissions
			frappe.throw(_("You are not permitted to request condonation for {0}.").format(frappe.bold(self.student)), frappe.PermissionError)
		self.company = student.oc_company

	def check_duplicate(self):
		if frappe.db.exists(
			"Condonation Request",
			{"student": self.student, "academic_term": self.academic_term, "docstatus": ["<", 2], "name": ["!=", self.name]},
		):
			frappe.throw(_("{0} already has a condonation request for {1}.").format(frappe.bold(self.student), self.academic_term))

	def check_band(self):
		"""Only the medical band may be condoned; the fee and the percentage are read from the current attendance."""
		summary = summarise(self.student, self.academic_term, term_window(self.academic_term), {})
		if summary["band_status"] == SHORTAGE:
			frappe.throw(_("{0} is below the medical band and is detained (SA); condonation is not available.").format(frappe.bold(self.student)))
		if summary["band_status"] != MEDICAL_BAND:
			frappe.throw(_("{0} meets the attendance requirement for {1}; no condonation is needed.").format(frappe.bold(self.student), self.academic_term))
		self.overall_pct = summary["overall_pct"]
		self.fee_amount = rule_values(self.student)["condonation_fee"]
