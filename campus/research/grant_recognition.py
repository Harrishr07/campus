"""M08-05 Grant income recognition (blueprint D9), the engine behind Grant Income Recognition.

Everything is cumulative to the period end, per sanction, read from the GL on the sanction's cost centre:
- revenue spent: the sanction's revenue head accounts; recognised by debiting the "Grant Received in Advance" liability
  and crediting the college's grant income account;
- capital spent (assets bought from the sanction): its capital head accounts (Fixed Asset ledgers); moved from the
  liability to the Deferred Capital Grant;
- depreciation: Depreciation accounts on the cost centre (ERPNext books an asset's depreciation on the asset's cost
  centre, which is the sanction's for an asset bought from it); the Deferred Capital Grant is released to grant income
  in line with it, never beyond what was capitalised (assets bought from a sanction are taken as wholly grant-funded).

What a run recognises is the cumulative amount less what earlier recognitions of the sanction already did, so a credit
note or a reversed depreciation reverses income, and spending back-dated into a recognised period is caught up by the
next period. A sanction is recognised once per period end: its row is locked and every fact re-read with locking reads,
and the recognition key (sanction, period end) is unique."""

import frappe
from frappe.query_builder.functions import Coalesce, Max, Sum
from frappe.utils import flt

from campus.research.api import head_accounts

SANCTION_FIELDS = ["name", "docstatus", "company", "liability_account", "cost_center", "project"]


def recognition_amounts(spent, done):
	"""What to post now. `spent`: cumulative revenue, capital and depreciation to the period end; `done`: revenue,
	capital and released already recognised. The release stops at what was capitalised."""
	release_to_date = min(flt(spent.depreciation), flt(spent.capital))
	return {
		"revenue": flt(flt(spent.revenue) - flt(done.revenue), 2),
		"capital": flt(flt(spent.capital) - flt(done.capital), 2),
		"release": flt(release_to_date - flt(done.released), 2),
	}


def lock_sanction(name):
	return frappe.db.get_value("Sanction", name, SANCTION_FIELDS, as_dict=True, for_update=True)


def spent_to(sanction, to_date, lock=False):
	"""Cumulative revenue, capital and depreciation posted on the sanction's cost centre up to `to_date`."""
	revenue, capital = [], []
	for row in frappe.get_all(
		"Sanction Head",
		{"parent": sanction.name, "parenttype": "Sanction"},
		["budget_head", "is_capital"],
		distinct=True,
	):
		(capital if row.is_capital else revenue).extend(head_accounts(row.budget_head, sanction.company))
	depreciation = frappe.get_all(
		"Account",
		{"company": sanction.company, "account_type": "Depreciation", "root_type": "Expense", "is_group": 0},
		pluck="name",
	)
	return frappe._dict(
		revenue=posted(sanction.cost_center, set(revenue), to_date, lock),
		capital=posted(sanction.cost_center, set(capital), to_date, lock),
		depreciation=posted(sanction.cost_center, set(depreciation), to_date, lock),
	)


def posted(cost_center, accounts, to_date, lock):
	"""Debit less credit on `accounts` and the cost centre (indexed) up to `to_date`."""
	if not accounts:
		return 0
	gl = frappe.qb.DocType("GL Entry")
	query = (
		frappe.qb.from_(gl)
		.select(Coalesce(Sum(gl.debit - gl.credit), 0))
		.where(
			(gl.cost_center == cost_center) & (gl.account.isin(list(accounts)))
			& (gl.is_cancelled == 0) & (gl.posting_date <= to_date)
		)
	)  # fmt: skip
	return flt((query.for_update() if lock else query).run()[0][0])


def recognised(sanction, lock=False):
	"""Revenue, capital and released already recognised for the sanction, and the latest period end."""
	row, doc = (
		frappe.qb.DocType("Grant Income Recognition Sanction"),
		frappe.qb.DocType("Grant Income Recognition"),
	)
	query = (
		frappe.qb.from_(row).join(doc).on(doc.name == row.parent)
		.select(
			Coalesce(Sum(row.revenue_amount), 0), Coalesce(Sum(row.capital_amount), 0),
			Coalesce(Sum(row.release_amount), 0), Max(doc.to_date),
		)
		.where((row.sanction == sanction) & (row.parenttype == "Grant Income Recognition") & (doc.docstatus == 1))
	)  # fmt: skip
	revenue, capital, released, last_to_date = (query.for_update() if lock else query).run()[0]
	return frappe._dict(
		revenue=flt(revenue), capital=flt(capital), released=flt(released), last_to_date=last_to_date
	)


def journal_rows(sanction, amounts, accounts):
	"""Balanced rows for one sanction: (debit account, credit account, amount) per movement, flipped when negative."""
	movements = (
		(sanction.liability_account, accounts.income, amounts["revenue"]),
		(sanction.liability_account, accounts.deferred, amounts["capital"]),
		(accounts.deferred, accounts.income, amounts["release"]),
	)
	rows = []
	for debit, credit, amount in movements:
		if not amount:
			continue
		if amount < 0:
			debit, credit, amount = credit, debit, -amount
		for account, side in ((debit, "debit_in_account_currency"), (credit, "credit_in_account_currency")):
			rows.append(
				{
					"account": account,
					side: amount,
					"cost_center": sanction.cost_center,
					"project": sanction.project,
				}
			)
	return rows
