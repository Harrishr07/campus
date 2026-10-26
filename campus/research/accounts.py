"""M08-01 Account checks shared by the research masters (blueprint D9 account roles)."""

import frappe
from frappe import _

# Revenue grant heads post spending, never depreciation, stock revaluation or rounding
NON_SPENDING_EXPENSE_TYPES = ("Depreciation", "Stock Adjustment", "Round Off")


def validate_account(account, company, label, root_type, is_group=0, account_type=None, excluded_types=()):
	"""Throw unless `account` is an enabled, unfrozen account of `company` with `root_type`, a group / ledger as asked,
	of `account_type` when given and of none of `excluded_types`."""
	row = frappe.db.get_value(
		"Account",
		account,
		["company", "root_type", "is_group", "account_type", "disabled", "freeze_account"],
		as_dict=True,
	)
	if not row or row.company != company:
		frappe.throw(_("{0}: account {1} does not belong to {2}.").format(label, account, company))
	if row.disabled:
		frappe.throw(_("{0}: account {1} is disabled.").format(label, account))
	if row.freeze_account == "Yes":
		frappe.throw(_("{0}: account {1} is frozen.").format(label, account))
	if bool(row.is_group) != bool(is_group):
		kind = _("group") if is_group else _("ledger")
		frappe.throw(_("{0}: account {1} must be a {2} account.").format(label, account, kind))
	if row.root_type != root_type:
		frappe.throw(_("{0}: account {1} must be of root type {2}.").format(label, account, _(root_type)))
	if account_type and row.account_type != account_type:
		frappe.throw(
			_("{0}: account {1} must be of account type {2}.").format(label, account, _(account_type))
		)
	if row.account_type in excluded_types:
		frappe.throw(
			_("{0}: account {1} can't be used, it is of account type {2}.").format(
				label, account, _(row.account_type)
			)
		)
