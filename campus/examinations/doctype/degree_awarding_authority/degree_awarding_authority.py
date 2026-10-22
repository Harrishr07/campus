"""M05-15 Degree Awarding Authority: who awards the degree of a programme of a college (the affiliating university or
the institution itself) and the Official Document (type and authority) that must be in force on the award date. One
per college and programme."""

import frappe
from frappe import _
from frappe.model.document import Document


class DegreeAwardingAuthority(Document):
	def validate(self):
		if frappe.db.get_value("Program", self.program, "oc_company") != self.company:
			frappe.throw(_("{0} is not a program of {1}.").format(frappe.bold(self.program), frappe.bold(self.company)))
		other = frappe.db.get_value(
			"Degree Awarding Authority", {"company": self.company, "program": self.program, "name": ["!=", self.name]}
		)
		if other:
			frappe.throw(_("{0} already sets the degree-awarding authority of {1}.").format(other, frappe.bold(self.program)))
