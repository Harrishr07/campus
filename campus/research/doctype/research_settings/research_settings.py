"""M08-01 Research Settings: per-college grant accounting accounts (blueprint D9), the default interest treatment and
the PFMS unique agency code, and the research cost centre each sanction's cost centre sits under (P3-T14)."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.research.accounts import validate_account


class ResearchSettings(Document):
	def validate(self):
		company = self.company
		validate_account(
			self.grant_liability_parent, company, _("Grant Liability Account Parent"), "Liability", 1
		)
		validate_account(self.grant_income_account, company, _("Grant Income Account"), "Income")
		validate_account(
			self.deferred_capital_grant_account, company, _("Deferred Capital Grant Account"), "Liability"
		)
		if self.research_cost_center:
			self.validate_research_cost_center()
		if self.interest_treatment == "Interest Income" and not self.interest_income_account:
			frappe.throw(_("Set the Interest Income Account when interest is treated as income."))
		if self.interest_income_account:
			validate_account(self.interest_income_account, company, _("Interest Income Account"), "Income")

	def validate_research_cost_center(self):
		row = frappe.db.get_value(
			"Cost Center", self.research_cost_center, ["company", "is_group", "disabled"], as_dict=True
		)
		if not row or row.company != self.company:
			frappe.throw(
				_("Research Cost Centre {0} does not belong to {1}.").format(
					self.research_cost_center, self.company
				)
			)
		if not row.is_group or row.disabled:
			frappe.throw(
				_("Research Cost Centre {0} must be an enabled group cost centre.").format(
					self.research_cost_center
				)
			)
