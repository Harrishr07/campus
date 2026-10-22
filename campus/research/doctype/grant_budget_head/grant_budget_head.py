"""M08-01 Grant Budget Head: a head (Equipment, Consumables, Manpower, ...) mapped per college to the ledger accounts
its spending posts to, and to item groups. Capital heads map to Fixed Asset ledgers and revenue heads to Expense ledgers
other than depreciation, stock adjustment and round off (blueprint D9)."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.research.accounts import NON_SPENDING_EXPENSE_TYPES, validate_account


class GrantBudgetHead(Document):
	def validate(self):
		if self.is_capital:
			rule = {"root_type": "Asset", "account_type": "Fixed Asset"}
		else:
			rule = {"root_type": "Expense", "excluded_types": NON_SPENDING_EXPENSE_TYPES}
		seen = set()
		for row in self.accounts:
			key = (row.company, row.account)
			if key in seen:
				frappe.throw(_("Row {0}: account {1} is mapped more than once.").format(row.idx, row.account))
			seen.add(key)
			validate_account(row.account, row.company, _("Row {0}").format(row.idx), **rule)
