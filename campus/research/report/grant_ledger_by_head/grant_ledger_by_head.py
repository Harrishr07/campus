"""M08-06 Grant Ledger by Head: the GL entries of a sanction's budget heads (each head's accounts on the sanction's
cost centre) for a period, per head: an opening row (spent before the period), the entries with a running balance and
a total row (spent in the period, the Utilisation Certificate's figure). Read through get_list, so User Permissions
apply."""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today

from campus.research.utilisation import sanction_heads

GL_FIELDS = ["posting_date", "account", "voucher_type", "voucher_no", "debit", "credit", "remarks"]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not (filters.company and filters.sanction):
		return columns(), []
	found = frappe.get_list(
		"Sanction", {"name": filters.sanction, "company": filters.company, "docstatus": 1},
		["name", "company", "cost_center", "start_date"],
	)  # fmt: skip
	if not found:
		return columns(), []
	sanction = found[0]
	from_date, to_date = (
		getdate(filters.from_date or sanction.start_date),
		getdate(filters.to_date or today()),
	)
	rows = []
	for head, values in sanction_heads(sanction).items():
		rows.extend(head_rows(sanction, head, values.accounts, from_date, to_date))
	return columns(), rows


def head_rows(sanction, head, accounts, from_date, to_date):
	entries = frappe.get_list(
		"GL Entry",
		{"company": sanction.company, "cost_center": sanction.cost_center, "account": ["in", list(accounts) or [""]],
		 "is_cancelled": 0, "posting_date": ["<=", to_date]},
		GL_FIELDS, order_by="posting_date asc, creation asc", limit=0,
	)  # fmt: skip
	opening = flt(
		sum(flt(e.debit) - flt(e.credit) for e in entries if getdate(e.posting_date) < from_date), 2
	)
	rows = [
		{
			"budget_head": head,
			"is_opening": 1,
			"voucher_type": _("Opening"),
			"posting_date": add_days(from_date, -1),
			"balance": opening,
		}
	]
	balance = opening
	for entry in entries:
		if getdate(entry.posting_date) < from_date:
			continue
		net = flt(flt(entry.debit) - flt(entry.credit), 2)
		balance = flt(balance + net, 2)
		rows.append({"budget_head": head, **entry, "net": net, "balance": balance})
	rows.append(
		{
			"budget_head": head,
			"is_total": 1,
			"voucher_type": _("Total"),
			"net": flt(balance - opening, 2),
			"balance": balance,
		}
	)
	return rows


def columns():
	def col(fieldname, label, fieldtype="Data", width=120, options=None):
		return {
			"fieldname": fieldname,
			"label": _(label),
			"fieldtype": fieldtype,
			"width": width,
			"options": options,
		}

	return [
		col("budget_head", "Budget Head", "Link", 150, "Grant Budget Head"),
		col("posting_date", "Posting Date", "Date", 100),
		col("account", "Account", "Link", 180, "Account"),
		col("voucher_type", "Voucher Type", width=130),
		col("voucher_no", "Voucher No", "Dynamic Link", 150, "voucher_type"),
		col("debit", "Debit", "Currency", 110),
		col("credit", "Credit", "Currency", 110),
		col("net", "Net", "Currency", 110),
		col("balance", "Spent to Date", "Currency", 120),
		col("remarks", "Remarks", width=200),
	]
