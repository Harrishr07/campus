"""M08-02 Research Call: an agency's call for proposals under one of its Funding Schemes, with the submission deadline
and how many days before it the PIs of open proposals are reminded (campus.research.proposals)."""

import frappe
from frappe import _
from frappe.model.document import Document


class ResearchCall(Document):
	def validate(self):
		scheme_agency = frappe.db.get_value("Funding Scheme", self.funding_scheme, "funding_agency")
		if scheme_agency != self.funding_agency:
			frappe.throw(
				_("Funding Scheme {0} belongs to {1}, not {2}.").format(self.funding_scheme, scheme_agency, self.funding_agency)
			)
