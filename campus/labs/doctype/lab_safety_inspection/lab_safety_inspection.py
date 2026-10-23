"""M12-05 Lab Safety Inspection: the lab is checked against a Safety Checklist Template and the outcome follows from the
points not met."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.labs.rules import inspection_outcome


class LabSafetyInspection(Document):
	def validate(self):
		self.check_template_company()
		if not self.results:
			self.fill_from_template()
		self.outcome = inspection_outcome(self.results)

	def check_template_company(self):
		lab_company = frappe.db.get_value("Laboratory", self.laboratory, "company")
		if frappe.db.get_value("Safety Checklist Template", self.template, "company") != lab_company:
			frappe.throw(_("Checklist template {0} belongs to another company").format(frappe.bold(self.template)))

	def fill_from_template(self):
		for item in frappe.get_doc("Safety Checklist Template", self.template).items:
			self.append("results", {"check_point": item.check_point, "critical": item.critical})
