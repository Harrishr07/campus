"""M03-03 CO Attainment Run: CO attainment of one course offering under its regulation's Attainment Policy, computed by
the bulk runner (campus.curriculum.attainment) with the policy values and an input snapshot; one live run per offering,
submitted once computed."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.curriculum import attainment


class COAttainmentRun(Document):
	def validate(self):
		attainment.set_co_scope(self)
		attainment.check_one_live(self, {"course_offering": self.course_offering}, ("Student Group", self.course_offering))

	def before_submit(self):
		if self.status != "Computed":
			frappe.throw(_("Compute the run before submitting it."))
