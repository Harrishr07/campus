"""M08-01 Account checks shared by the research masters (blueprint D9 account roles)."""

import frappe
from frappe import _


def validate_account(account, company, label, root_type, is_group=0):
	"""Throw unless `account` belongs to `company`, has `root_type` and is a group / ledger as asked."""
	row = frappe.db.get_value("Account", account, ["company", "root_type", "is_group"], as_dict=True)
	if not row or row.company != company:
		frappe.throw(_("{0}: account {1} does not belong to {2}.").format(label, account, company))
	if bool(row.is_group) != bool(is_group):
		kind = _("group") if is_group else _("ledger")
		frappe.throw(_("{0}: account {1} must be a {2} account.").format(label, account, kind))
	if row.root_type != root_type:
		frappe.throw(_("{0}: account {1} must be of root type {2}.").format(label, account, _(root_type)))
