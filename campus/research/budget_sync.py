"""M08-04 Keep a sanction's ERPNext Budgets in line with its heads (P3-T15).

After a re-appropriation or an extension, each revenue head account's Budget must hold the head's per-year amounts and
run to the fiscal year of the (possibly revised) end date. A Budget that differs is cancelled and replaced by a new
one (its revision_of names the old), the ERPNext way to revise a submitted Budget. An extension into a new fiscal year
adds that year with nothing new sanctioned, so the unspent balance can be spent there (ERPNext checks the amount
sanctioned to date). A head left with nothing loses its Budget, and its lines are then refused (budget_control).

Reads are locking: the caller's view of the sanction may predate a concurrent re-appropriation."""

import frappe
from frappe.utils import flt

from campus.research.grant_setup import GrantSetup

SANCTION_FIELDS = ["name", "company", "funding_scheme", "cost_center", "start_date", "end_date"]


def sync_budgets(sanction_name):
	sanction = locked_sanction(sanction_name)
	setup = GrantSetup(sanction)
	wanted = setup.revenue_budget_lines()
	to_year = setup.fiscal_year(sanction.end_date)
	existing = dict(
		frappe.get_all("Budget", {"cost_center": sanction.cost_center, "docstatus": 1}, ["account", "name"], as_list=True)
	)
	action = frappe.db.get_value("Funding Scheme", sanction.funding_scheme, "budget_action") or "Stop"
	for account in sorted(set(wanted) | set(existing)):
		per_year = {year: amount for year, amount in wanted.get(account, {}).items() if flt(amount)}
		old = existing.get(account)
		if old and is_current(setup, old, per_year, to_year):
			continue
		if old:
			budget = frappe.get_doc("Budget", old)
			budget.flags.ignore_permissions = True
			budget.cancel()
		if per_year:
			new = setup.make_budget(account, per_year, action)
			if old:
				frappe.db.set_value("Budget", new, "revision_of", old)


def locked_sanction(name):
	sanction = frappe.db.get_value("Sanction", name, SANCTION_FIELDS, as_dict=True, for_update=True)
	row = frappe.qb.DocType("Sanction Head")
	sanction.heads = (
		frappe.qb.from_(row)
		.select(row.budget_head, row.fiscal_year, row.amount, row.is_capital)
		.where((row.parent == name) & (row.parenttype == "Sanction"))
		.orderby(row.idx)
		.for_update()
		.run(as_dict=True)
	)
	return sanction


def is_current(setup, budget_name, per_year, to_year):
	budget = frappe.get_doc("Budget", budget_name)
	if budget.to_fiscal_year != to_year:
		return False
	held = {setup.fiscal_year(row.start_date): flt(row.amount, 2) for row in budget.budget_distribution if flt(row.amount)}
	return held == {year: flt(amount, 2) for year, amount in per_year.items()}
