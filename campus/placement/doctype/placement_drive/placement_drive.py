"""M14-01 Placement Drive: a recruiter's visit with roles and CTC, eligibility criteria, selection rounds and a schedule.

The criteria are applied live (campus.placement.eligibility): nothing about a student's eligibility is stored on the
drive. Choosing an eligibility template copies its criteria into the drive, which may then be adjusted."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.placement.eligibility import template_values
from campus.placement.doctype.recruiter.recruiter import MOU_DEAD


class PlacementDrive(Document):
	def validate(self):
		self.apply_template()
		self.check_recruiter()
		self.check_rounds()
		self.check_criteria()
		if self.status != "Draft":
			self.check_ready()

	def apply_template(self):
		"""A new drive that names a template and sets no criteria of its own takes the template's; criteria typed or sent
		with the drive are kept (the form copies a template's criteria when it is chosen)."""
		if not self.eligibility_template:
			return
		company = frappe.db.get_value("Placement Eligibility Template", self.eligibility_template, "company")
		if company != self.company:
			frappe.throw(_("Template {0} belongs to {1}, not {2}").format(self.eligibility_template, company, self.company))
		if self.is_new() and self.criteria_untouched():
			self.update(template_values(self.eligibility_template))

	def criteria_untouched(self):
		return not (
			self.min_cgpa or self.any_standing_arrears or self.max_standing_arrears or self.gender or self.programs or self.batches
		)

	def check_recruiter(self):
		company, disabled, mou = frappe.db.get_value("Recruiter", self.recruiter, ["company", "disabled", "mou"])
		if company != self.company:
			frappe.throw(_("Recruiter {0} belongs to {1}, not {2}").format(self.recruiter, company, self.company))
		if disabled and self.has_value_changed("recruiter"):
			frappe.throw(_("Recruiter {0} is disabled").format(self.recruiter))
		if self.status == "Open" and mou and frappe.db.get_value("Institutional MoU", mou, "status") in MOU_DEAD:
			frappe.throw(_("The MoU {0} with {1} is no longer in force").format(mou, self.recruiter))

	def check_rounds(self):
		numbers = [row.round_no for row in self.rounds]
		if len(set(numbers)) != len(numbers) or any(number < 1 for number in numbers):
			frappe.throw(_("Round numbers must be unique and start from 1"))
		self.rounds.sort(key=lambda row: row.round_no)

	def check_criteria(self):
		if frappe.utils.flt(self.min_cgpa) < 0 or frappe.utils.cint(self.max_standing_arrears) < 0:
			frappe.throw(_("Minimum CGPA and standing arrears allowed cannot be negative"))

	def check_ready(self):
		if self.status in ("Open", "Closed", "Completed") and not self.roles:
			frappe.throw(_("Add at least one role before the drive is opened"))
