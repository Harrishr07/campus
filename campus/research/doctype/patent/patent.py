"""M08-11 Patent: the filing of an approved Invention Disclosure and its life: Filed, Published, Examined, Granted, Licensed.

Each stage needs its date and a patent never goes back a stage. Costs are recorded as incurred. Licence revenue can be
recorded once granted (the patent becomes Licensed) and is split between the institution (this patent's share %) and
the inventors; `inventor_shares` divides the inventors' part by the shares on the disclosure."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from campus.research.ipr import LICENSABLE, STAGE_DATES, check_lifecycle, split_among, split_revenue


class Patent(Document):
	def validate(self):
		self.check_disclosure()
		self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		self.check_share()
		if self.status in LICENSABLE and not self.patent_number:
			frappe.throw(_("Enter the patent number of a granted patent."))
		self.set_licensed()
		check_lifecycle(
			self.status,
			{field: self.get(field) for field in STAGE_DATES.values()},
			self.status_before(),
			today(),
		)
		self.set_totals()

	def check_disclosure(self):
		disclosure = frappe.db.get_value(
			"Invention Disclosure",
			self.invention_disclosure,
			["docstatus", "title", "company", "department", "ipr_type"],
			as_dict=True,
		)
		if not disclosure or (disclosure.docstatus != 1 and self.is_linking_or_advancing()):
			frappe.throw(
				_("Invention Disclosure {0} must be approved and submitted before it is filed.").format(
					self.invention_disclosure
				)
			)
		for field in (
			"title",
			"company",
			"department",
			"ipr_type",
		):  # also what fetch_from fills, which runs after validate
			self.set(field, disclosure[field])
		if (
			self.get_doc_before_save()
			and self.get_doc_before_save().invention_disclosure != self.invention_disclosure
		):
			frappe.throw(_("The Invention Disclosure of a patent can't be changed."))

	def is_linking_or_advancing(self):
		"""A new patent, a new disclosure or a new stage needs an approved disclosure; a later cancel of the disclosure
		doesn't stop the patent being updated (costs, revenue) without a change of stage."""
		before = self.get_doc_before_save()
		return (
			not before
			or before.invention_disclosure != self.invention_disclosure
			or before.status != self.status
		)

	def check_share(self):
		if not 0 <= flt(self.institution_share_percent) <= 100:
			frappe.throw(_("The institution's share must be between 0 and 100%."))

	def status_before(self):
		before = self.get_doc_before_save()
		return before.status if before else None

	def set_licensed(self):
		"""Licence revenue moves a granted patent to Licensed, and is only possible once it is granted."""
		if self.licences and self.status not in LICENSABLE:
			frappe.throw(_("Licence revenue can be recorded only for a granted patent."))
		if self.licences and self.status == "Granted":
			self.status = "Licensed"
		for row in self.licences:
			if flt(row.amount_received) <= 0:
				frappe.throw(_("Row {0}: the revenue received must be above zero.").format(row.idx))
			if self.granted_date and getdate(row.licence_date) < getdate(self.granted_date):
				frappe.throw(
					_("Row {0}: revenue can't be received before the patent was granted.").format(row.idx)
				)

	def set_totals(self):
		for row in self.costs:
			if flt(row.amount) <= 0:
				frappe.throw(_("Row {0}: the cost must be above zero.").format(row.idx))
		self.total_cost = sum(flt(row.amount) for row in self.costs)
		for row in self.licences:
			row.institution_amount, row.inventors_amount = split_revenue(
				row.amount_received, self.institution_share_percent
			)
		self.total_revenue = sum(flt(row.amount_received) for row in self.licences)
		self.institution_revenue = sum(flt(row.institution_amount) for row in self.licences)
		self.inventors_revenue = sum(flt(row.inventors_amount) for row in self.licences)

	def inventor_shares(self):
		"""[{inventor_type, employee, student, inventor_name, amount}] dividing the inventors' revenue by their disclosure shares."""
		inventors = frappe.get_all(
			"IPR Inventor",
			{"parent": self.invention_disclosure, "parenttype": "Invention Disclosure"},
			["inventor_type", "employee", "student", "inventor_name", "share_percent"],
			order_by="idx",
		)
		amounts = split_among(flt(self.inventors_revenue), [row.share_percent for row in inventors])
		return [
			{key: row[key] for key in ("inventor_type", "employee", "student", "inventor_name")}
			| {"amount": amount}
			for row, amount in zip(inventors, amounts, strict=True)
		]
