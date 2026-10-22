"""M14-01 Recruiter: a company that recruits from a college, with contacts and the Institutional MoU (P3-T08) that
covers the relationship."""

import frappe
from frappe import _
from frappe.model.document import Document

MOU_DEAD = ("Terminated", "Expired")


class Recruiter(Document):
	def validate(self):
		self.check_unique()
		self.check_mou()

	def check_unique(self):
		clash = frappe.db.exists(
			"Recruiter", {"company": self.company, "recruiter_name": self.recruiter_name, "name": ["!=", self.name]}
		)
		if clash:
			frappe.throw(_("{0} already has a recruiter named {1} ({2})").format(self.company, self.recruiter_name, clash))

	def check_mou(self):
		if not self.mou:
			return
		company, status = frappe.db.get_value("Institutional MoU", self.mou, ["company", "status"])
		if company != self.company:
			frappe.throw(_("MoU {0} belongs to {1}, not {2}").format(self.mou, company, self.company))
		if status in MOU_DEAD and self.has_value_changed("mou"):
			frappe.throw(_("MoU {0} is {1}").format(self.mou, _(status)))
