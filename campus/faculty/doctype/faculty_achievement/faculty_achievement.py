"""M07-04 Faculty Achievement: a faculty member's non-training achievement (conference, resource person, award,
membership, certification) with private evidence and the financial support given. FDP attendance is not entered here: it
stays in the HRMS Training Event (campus.faculty.self_appraisal reads it from there). HR verifies; only verified
achievements score in the self-appraisal or count in the NAAC 6.3.2 report.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.faculty.self_appraisal import is_hr

SCORED_FIELDS = ("achievement_type", "achievement_date", "title", "financial_support_amount", "evidence", "training_event")


class FacultyAchievement(Document):
	def validate(self):
		self.check_filer()
		self.check_evidence()
		self.check_training_event()
		self.reset_verification_on_change()
		self.check_verification()

	def check_filer(self):
		"""Faculty file for themselves; HR may file for anyone."""
		user = frappe.session.user
		if is_hr(user):
			return
		if frappe.db.get_value("Employee", self.employee, "user_id") != user:
			frappe.throw(_("You can only record your own achievements."), frappe.PermissionError)

	def check_evidence(self):
		if self.evidence and not self.evidence.startswith("/private/"):
			frappe.throw(_("Evidence must be a private file. Attach it as a private file."))

	def check_training_event(self):
		"""FDP attendance lives in the Training Event, so a Conference cannot be filed against an FDP (it would score twice)."""
		if self.achievement_type == "Conference" and self.training_event and frappe.db.get_value("Training Event", self.training_event, "oc_is_fdp"):
			frappe.throw(_("{0} is an FDP: its attendance is counted from the Training Event, not as a Conference.").format(self.training_event))

	def reset_verification_on_change(self):
		"""A verified achievement stays verified only as HR saw it: anyone else changing what is scored has to be verified again."""
		before = self.get_doc_before_save()
		if not (before and before.verified) or is_hr():
			return
		if any(self.get(f) != before.get(f) for f in SCORED_FIELDS):
			self.verified = 0
			frappe.msgprint(_("The achievement was changed, so HR has to verify it again."), indicator="orange")

	def check_verification(self):
		if self.verified and not self.evidence:
			frappe.throw(_("Attach the evidence before verifying the achievement."))
