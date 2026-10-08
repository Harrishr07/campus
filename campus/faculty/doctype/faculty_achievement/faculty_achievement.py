"""M07-04 Faculty Achievement: a faculty member's non-training achievement (conference, resource person, award,
membership, certification) with private evidence and the financial support given. FDP attendance is not entered here: it
stays in the HRMS Training Event (campus.faculty.self_appraisal reads it from there). HR verifies; only verified
achievements score in the self-appraisal or count in the NAAC 6.3.2 report.
"""

import frappe
from frappe import _
from frappe.model.document import Document

HR_ROLES = ("System Manager", "HR Manager", "HR User")


class FacultyAchievement(Document):
	def validate(self):
		self.check_filer()
		self.check_evidence()
		self.check_verification()

	def check_filer(self):
		"""Faculty file for themselves; HR may file for anyone."""
		user = frappe.session.user
		if user == "Administrator" or set(HR_ROLES) & set(frappe.get_roles(user)):
			return
		if frappe.db.get_value("Employee", self.employee, "user_id") != user:
			frappe.throw(_("You can only record your own achievements."), frappe.PermissionError)

	def check_evidence(self):
		if self.evidence and not self.evidence.startswith("/private/"):
			frappe.throw(_("Evidence must be a private file. Attach it as a private file."))

	def check_verification(self):
		if self.verified and not self.evidence:
			frappe.throw(_("Attach the evidence before verifying the achievement."))
