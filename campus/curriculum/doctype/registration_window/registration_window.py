"""M03-04 Registration Window: when a term's course registration is open, with optional overrides."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class RegistrationWindow(Document):
	def validate(self):
		if getdate(self.closes_on) < getdate(self.opens_on):
			frappe.throw(_("Closes On cannot be before Opens On."))
		if self.drop_until and getdate(self.drop_until) < getdate(self.opens_on):
			frappe.throw(_("Drop Until cannot be before Opens On."))
		if self.program and frappe.db.get_value("Program", self.program, "oc_company") != self.company:
			frappe.throw(_("Programme {0} belongs to another company.").format(frappe.bold(self.program)))
		duplicate = frappe.db.exists(
			"Registration Window",
			{
				"academic_term": self.academic_term, "company": self.company,
				"program": self.program or ["is", "not set"], "name": ["!=", self.name or ""],
			},
		)  # fmt: skip
		if duplicate:
			frappe.throw(_("{0} already covers this term and programme.").format(duplicate))
