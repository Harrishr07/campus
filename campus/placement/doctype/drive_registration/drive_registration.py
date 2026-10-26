"""M14-01 Drive Registration: a student's opt-in to a drive. Only a student on the roll of the drive's college who
meets the drive's criteria NOW (live results) may register, while the drive is Open and before its deadline. The CGPA
and arrears seen at registration are kept as evidence; eligibility itself is always re-read live."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import has_user_permission
from frappe.utils import now_datetime

from campus.placement import eligibility
from campus.placement.api import deadline_passed

SNAPSHOT = ("cgpa", "standing_arrears", "had_arrears", "registered_on")


class DriveRegistration(Document):
	def validate(self):
		drive = frappe.get_doc("Placement Drive", self.drive)
		if not has_user_permission(drive):  # Company User Permissions
			frappe.throw(
				_("You have no access to {0} placement drives").format(drive.company), frappe.PermissionError
			)
		self.company = drive.company
		if self.status == "Registered" and (self.is_new() or self.has_value_changed("status")):
			self.check_open(drive)
			self.take_snapshot()
		else:
			self.keep_snapshot()
			if self.status == "Withdrawn":
				self.check_not_shortlisted()

	def keep_snapshot(self):
		"""The standing seen at registration is evidence: never taken from the request."""
		for field in SNAPSHOT:
			self.set(field, None if self.is_new() else self.get_db_value(field))

	def on_trash(self):
		self.check_not_shortlisted()

	def check_open(self, drive):
		if drive.status != "Open":
			frappe.throw(_("{0} is not open for registration").format(self.drive))
		if deadline_passed(drive.registration_deadline):
			frappe.throw(
				_("Registration for {0} closed on {1}").format(
					self.drive, frappe.format(drive.registration_deadline, {"fieldtype": "Datetime"})
				)
			)

	def take_snapshot(self):
		result = eligibility.evaluate(self.drive, self.student)
		if not result["eligible"]:
			frappe.throw(
				_("{0} is not eligible for {1}:").format(self.student, self.drive)
				+ "<br>"
				+ "<br>".join(result["reasons"])
			)
		self.cgpa, self.standing_arrears, self.had_arrears = (
			result["cgpa"],
			result["standing_arrears"],
			result["had_arrears"],
		)
		self.registered_on = now_datetime()

	def check_not_shortlisted(self):
		rounds = frappe.get_all("Round Result", {"drive": self.drive}, pluck="name")
		if rounds and frappe.db.exists(
			"Round Result Student",
			{"student": self.student, "parenttype": "Round Result", "parent": ["in", rounds]},
		):
			frappe.throw(
				_("{0} appears in a round result of {1} and cannot withdraw").format(self.student, self.drive)
			)
