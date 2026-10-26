"""M17-01 / D8 Shared Service Agreement: which Company provides a service to which colleges."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class SharedServiceAgreement(Document):
	def validate(self):
		self.invoicing_company = self.invoicing_company or self.provider_company
		self.validate_dates()
		self.validate_members()
		self.validate_no_overlap()

	def validate_dates(self):
		if self.to_date and getdate(self.to_date) < getdate(self.from_date):
			frappe.throw(_("To Date cannot be before From Date"))

	def validate_members(self):
		members = [m.company for m in self.members]
		if len(members) != len(set(members)):
			frappe.throw(_("A member company is listed more than once"))

	def validate_no_overlap(self):
		"""One service has one provider per member at any time, so lookups are unambiguous."""
		members = [m.company for m in self.members]
		others = frappe.get_all(
			"Shared Service Member",
			filters={
				"company": ["in", members],
				"parenttype": self.doctype,
				"parent": ["!=", self.name or ""],
			},
			fields=["parent", "company"],
		)
		for other in others:
			agreement = frappe.db.get_value(
				"Shared Service Agreement", other.parent, ["service", "from_date", "to_date"], as_dict=True
			)
			if agreement.service == self.service and self.overlaps(agreement):
				frappe.throw(
					_("{0} already has a {1} agreement ({2}) covering these dates").format(
						other.company, self.service, other.parent
					)
				)

	def overlaps(self, other):
		starts_before_other_ends = not other.to_date or getdate(self.from_date) <= getdate(other.to_date)
		ends_after_other_starts = not self.to_date or getdate(self.to_date) >= getdate(other.from_date)
		return starts_before_other_ends and ends_after_other_starts
