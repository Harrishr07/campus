"""M08-01 Research Settings: per-college grant accounting accounts (blueprint D9), the default interest treatment and
the PFMS unique agency code."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.research.accounts import validate_account


class ResearchSettings(Document):
	def validate(self):
		company = self.company
		validate_account(self.grant_liability_parent, company, _("Grant Liability Account Parent"), "Liability", 1)
		validate_account(self.grant_income_account, company, _("Grant Income Account"), "Income")
		validate_account(self.deferred_capital_grant_account, company, _("Deferred Capital Grant Account"), "Liability")
		if self.interest_treatment == "Interest Income" and not self.interest_income_account:
			frappe.throw(_("Set the Interest Income Account when interest is treated as income."))
		if self.interest_income_account:
			validate_account(self.interest_income_account, company, _("Interest Income Account"), "Income")
