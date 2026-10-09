"""M08-03, M08-05 Sanction: an agency's grant to a college's project (order no/date, agency and scheme, PI and co-PIs,
duration, sanctioned amount per head per fiscal year, instalments, conditions). The scheme must be usable by the
college (campus.research.api.validate_scheme_usable). A sanction may come from a Sanctioned Research Proposal.

Submitting it sets up the ERPNext records the grant is run on (campus.research.grant_setup, blueprint D9): a Project, a
Cost Center under the research cost centre, a Budget per revenue head account and the liability account "Grant Received
in Advance - <sanction>". Cancelling it before any transaction removes them. Grant Receipts credit that liability.
`extend_sanction` revises the end date with the agency's extension order.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from campus.research.api import head_accounts, validate_scheme_usable
from campus.research.grant_setup import GrantSetup


class Sanction(Document):
	def validate(self):
		self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		self.total_sanctioned = sum(flt(row.amount) for row in self.heads)
		validate_scheme_usable(self.funding_scheme, self.company)
		self.check_scheme_agency()
		self.check_period()
		self.check_investigators()
		self.check_heads()
		self.check_instalments()
		if self.research_proposal:
			self.check_proposal()

	def before_submit(self):
		if self.research_proposal:
			self.check_proposal(lock=True)
		GrantSetup(self).create()

	def on_cancel(self):
		GrantSetup(self).remove()

	@frappe.whitelist()
	def extend_sanction(self, revised_end_date, order_no, order_date):
		"""Revise the end date under the agency's extension order; the Project's end date follows."""
		self.check_permission("submit")
		if self.docstatus != 1:
			frappe.throw(_("Only a submitted sanction can be extended."))
		current = getdate(frappe.db.get_value(self.doctype, self.name, "end_date", for_update=True))
		revised = getdate(revised_end_date)
		if revised <= current:
			frappe.throw(_("The revised end date must be after the current end date {0}.").format(frappe.format(current, "Date")))
		if not order_no or not order_date:
			frappe.throw(_("Enter the extension order number and date."))
		row = self.append(
			"extensions",
			{"order_no": order_no, "order_date": getdate(order_date), "previous_end_date": current, "revised_end_date": revised},
		)
		row.db_insert()
		self.db_set("end_date", revised)
		frappe.db.set_value("Project", self.project, "expected_end_date", revised)
		self.add_comment(
			"Info", _("Extended to {0} under order {1}.").format(frappe.format(revised, "Date"), order_no)
		)

	def check_scheme_agency(self):
		agency = frappe.db.get_value("Funding Scheme", self.funding_scheme, "funding_agency")
		if agency != self.funding_agency:
			frappe.throw(
				_("Funding Scheme {0} belongs to {1}, not {2}.").format(self.funding_scheme, agency, self.funding_agency)
			)

	def check_period(self):
		if getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("The end date can't be before the start date."))

	def check_investigators(self):
		co_pis = [row.employee for row in self.co_investigators]
		if self.principal_investigator in co_pis:
			frappe.throw(_("The principal investigator can't also be a co-investigator."))
		if len(set(co_pis)) != len(co_pis):
			frappe.throw(_("A co-investigator is listed more than once."))
		everyone = [self.principal_investigator, *co_pis]
		companies = dict(frappe.get_all("Employee", {"name": ["in", everyone]}, ["name", "company"], as_list=True))
		outside = [e for e in everyone if companies.get(e) != self.company]
		if outside:
			frappe.throw(_("Investigators {0} are not employees of {1}.").format(", ".join(outside), self.company))

	def check_heads(self):
		scheme_heads = set(
			frappe.get_all(
				"Funding Scheme Head", {"parent": self.funding_scheme, "parenttype": "Funding Scheme"}, pluck="budget_head"
			)
		)
		seen = set()
		for row in self.heads:
			if row.budget_head not in scheme_heads:
				frappe.throw(
					_("Row {0}: {1} is not a budget head of Funding Scheme {2}.").format(row.idx, row.budget_head, self.funding_scheme)
				)
			if (row.budget_head, row.fiscal_year) in seen:
				frappe.throw(
					_("Row {0}: {1} is listed more than once for {2}.").format(row.idx, row.budget_head, row.fiscal_year)
				)
			seen.add((row.budget_head, row.fiscal_year))
			if flt(row.amount) <= 0:
				frappe.throw(_("Row {0}: enter an amount for {1}.").format(row.idx, row.budget_head))
			self.check_fiscal_year(row)
			row.is_capital = frappe.db.get_value("Grant Budget Head", row.budget_head, "is_capital")
		self.check_revenue_head_accounts()

	def check_fiscal_year(self, row):
		year = frappe.db.get_value("Fiscal Year", row.fiscal_year, ["year_start_date", "year_end_date"], as_dict=True)
		if not year:
			frappe.throw(_("Row {0}: fiscal year {1} does not exist.").format(row.idx, row.fiscal_year))
		if getdate(year.year_start_date) > getdate(self.end_date) or getdate(year.year_end_date) < getdate(self.start_date):
			frappe.throw(_("Row {0}: fiscal year {1} is outside the sanction period.").format(row.idx, row.fiscal_year))
		companies = frappe.get_all("Fiscal Year Company", {"parent": row.fiscal_year}, pluck="company")
		if companies and self.company not in companies:
			frappe.throw(_("Row {0}: fiscal year {1} is not available for {2}.").format(row.idx, row.fiscal_year, self.company))

	def check_revenue_head_accounts(self):
		"""ERPNext Budget is per account: each revenue head needs its own single account so the Budget is the head's."""
		owner = {}
		for head in {row.budget_head for row in self.heads if not row.is_capital}:
			accounts = head_accounts(head, self.company)
			if len(accounts) != 1:
				frappe.throw(
					_("Revenue head {0} must map to one account of {1} for its budget; it maps to {2}.").format(
						head, self.company, len(accounts)
					)
				)
			if accounts[0] in owner:
				frappe.throw(
					_("Revenue heads {0} and {1} map to the same account {2}.").format(owner[accounts[0]], head, accounts[0])
				)
			owner[accounts[0]] = head

	def check_instalments(self):
		labels = [row.instalment for row in self.instalments]
		if len(set(labels)) != len(labels):
			frappe.throw(_("An instalment is listed more than once."))
		for row in self.instalments:
			if flt(row.amount) <= 0:
				frappe.throw(_("Row {0}: enter an amount for instalment {1}.").format(row.idx, row.instalment))
		total = sum(flt(row.amount) for row in self.instalments)
		if flt(total, 2) != flt(self.total_sanctioned, 2):
			frappe.throw(
				_("Instalments add up to {0}, not the sanctioned total {1}.").format(
					frappe.format(total, "Currency"), frappe.format(self.total_sanctioned, "Currency")
				)
			)

	def check_proposal(self, lock=False):
		"""The proposal must be Sanctioned, for this college and scheme, and not already have a submitted sanction."""
		proposal = frappe.db.get_value(
			"Research Proposal", self.research_proposal, ["company", "funding_scheme", "status", "docstatus"],
			as_dict=True, for_update=lock,
		)  # fmt: skip
		if proposal.docstatus != 1 or proposal.status != "Sanctioned":
			frappe.throw(_("Research Proposal {0} is not sanctioned by the agency.").format(self.research_proposal))
		if (proposal.company, proposal.funding_scheme) != (self.company, self.funding_scheme):
			frappe.throw(
				_("Research Proposal {0} is for {1} of {2}, not {3} of {4}.").format(
					self.research_proposal, proposal.funding_scheme, proposal.company, self.funding_scheme, self.company
				)
			)
		existing = frappe.db.get_value(
			"Sanction", {"research_proposal": self.research_proposal, "docstatus": 1, "name": ["!=", self.name]},
			"name", for_update=lock,
		)  # fmt: skip
		if existing:
			frappe.throw(_("Research Proposal {0} already has Sanction {1}.").format(self.research_proposal, existing))
