"""M08-01 Grant Budget Head: a head (Equipment, Consumables, Manpower, ...) mapped per college to the ledger accounts
its spending posts to, and to item groups. Capital heads map to Asset accounts and revenue heads to Expense accounts
(blueprint D9)."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.research.accounts import validate_account


class GrantBudgetHead(Document):
	def validate(self):
		root_type = "Asset" if self.is_capital else "Expense"
		seen = set()
		for row in self.accounts:
			key = (row.company, row.account)
			if key in seen:
				frappe.throw(_("Row {0}: account {1} is mapped more than once.").format(row.idx, row.account))
			seen.add(key)
			validate_account(row.account, row.company, _("Row {0}").format(row.idx), root_type)
