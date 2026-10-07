"""M05-06 Student Grievance: a student's complaint, routed up an escalation chain by the approval engine.

The category (HRMS Grievance Type, extended with oc_ fields) names the escalation Approval Policy and says
whether the grievance is confidential. Raising a grievance starts an approval request under that policy:
its levels (HOD, COE, Principal...) are the escalation chain and each level's SLA hours drive
`grievances.escalate_overdue`. A handler resolves it (`grievances.resolve`), which closes the request and
submits the document; submitting is resolving.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission
from frappe.utils import now_datetime

from campus.campus_platform.api import ApprovableDocument
from campus.campus_platform.approval_engine import start_request
from campus.student_services import grievances


class StudentGrievance(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		if self.is_new():
			self.set_context()
			self.raised_on = now_datetime()
			self.status = "Open"

	def set_context(self):
		student = frappe.get_doc("Student", self.student)
		if not has_user_permission(student):  # Company User Permissions
			frappe.throw(_("You are not permitted to raise a grievance for {0}.").format(frappe.bold(self.student)), frappe.PermissionError)
		self.company = student.oc_company
		self.department = grievances.student_department(self.student)
		category = grievances.category_settings(self.category)
		self.is_confidential = category.oc_confidential
		self.escalation_policy = category.oc_escalation_policy

	def after_insert(self):
		start_request(self, frappe.get_doc("Approval Policy", self.escalation_policy))

	def before_submit(self):
		super().before_submit()
		if not (self.resolution or "").strip():
			frappe.throw(_("Give the resolution before closing the grievance."))
		self.status = "Resolved"
		self.resolved_on = now_datetime()
		self.resolved_by = frappe.session.user

	def on_cancel(self):
		self.db_set("status", "Cancelled")
