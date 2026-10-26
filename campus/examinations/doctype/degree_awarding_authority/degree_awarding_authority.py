"""M05-15 Degree Awarding Authority: who awards the degree of a programme of a college (the affiliating university or
the institution itself) and the Official Document (type and authority) that must be in force on the award date. One
per college and programme. Kept by the Principal or System Manager, not by the COE / Dean it gates, and the document
must fit the awarding body (PAIRINGS)."""

import frappe
from frappe import _
from frappe.model.document import Document

PAIRINGS = {  # awarding body -> (document authority, document types)
	"Affiliating University": ("University", ("Affiliation",)),
	"Institution": ("UGC", ("Recognition", "Approval")),
}


class DegreeAwardingAuthority(Document):
	def validate(self):
		if frappe.db.get_value("Program", self.program, "oc_company") != self.company:
			frappe.throw(
				_("{0} is not a program of {1}.").format(frappe.bold(self.program), frappe.bold(self.company))
			)
		authority, types = PAIRINGS[self.awarding_body]
		if self.document_authority != authority or self.document_type not in types:
			frappe.throw(
				_("A degree awarded by the {0} needs {1} of {2} on the Official Document register.").format(
					_(self.awarding_body), " / ".join(_(t) for t in types), authority
				)
			)
		other = frappe.db.get_value(
			"Degree Awarding Authority",
			{"company": self.company, "program": self.program, "name": ["!=", self.name]},
		)
		if other:
			frappe.throw(
				_("{0} already sets the degree-awarding authority of {1}.").format(
					other, frappe.bold(self.program)
				)
			)
