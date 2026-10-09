"""M08-06 Utilisation Certificate figures, the reconciliation gate and the "source changed" check (blueprint D9).

Everything is read from the GL of the sanction:
- the "Grant Received in Advance" liability: credits from Grant Receipts (grants received), from Grant Interest (interest
  under the Grant Liability treatment) and anything else posted to it, such as a refund to the agency (other
  adjustments). Grant Income Recognition entries only move money already spent out of the liability and are left out;
- expenditure by head: debit less credit on each budget head's accounts on the sanction's cost centre (capital heads at
  cost; depreciation is not expenditure).

Opening unspent = what came in before the period less what was spent before it; closing unspent = total available less
the period's expenditure, so it equals all inflows less all spending up to the period end.

Spending on the sanction's project or cost centre that the heads don't account for (an expense or fixed asset ledger
outside every head of the sanction, or on the project under another cost centre) is unreconciled: the UC can't be
approved while any exists up to its period end.

An approved UC keeps a snapshot of its figures. Any GL entry on its liability, cost centre or project dated up to its
period end recomputes it, and a difference marks it "source changed"; the approved figures stay as they were."""

import json

import frappe
from frappe import _
from frappe.query_builder.functions import Coalesce, Sum
from frappe.utils import add_days, flt, getdate, now_datetime

from campus.research.accounts import NON_SPENDING_EXPENSE_TYPES
from campus.research.api import head_accounts
from campus.research.grant_recognition import posted

UC_DOCTYPE = "Utilisation Certificate"
UC_POLICY = "Utilisation Certificate Approval"
ENGINE_VERSION = 1
SANCTION_FIELDS = ["name", "company", "liability_account", "cost_center", "project", "start_date", "end_date"]
FIGURE_FIELDS = (
	"opening_unspent", "grants_received", "interest_earned", "other_adjustments", "total_available",
	"total_expenditure", "closing_unspent", "unreconciled_amount",
)  # fmt: skip
HEAD_FIELDS = ("budget_head", "is_capital", "sanctioned_amount", "spent_before", "spent_in_period", "spent_to_date", "balance")


# figures
def utilisation_figures(sanction, from_date, to_date, lock=False):
	"""The UC figures of `sanction` (a name) for the period, heads in sanction order and the unreconciled entries."""
	sanction = frappe.db.get_value("Sanction", sanction, SANCTION_FIELDS, as_dict=True)
	before = add_days(from_date, -1)
	inflow_before, inflow = liability_inflows(sanction, from_date, to_date, lock)
	heads = head_figures(sanction, before, to_date, lock)
	unreconciled = unreconciled_entries(sanction, to_date, lock)
	figures = frappe._dict(
		opening_unspent=flt(sum(inflow_before.values()) - sum(h.spent_before for h in heads), 2),
		grants_received=inflow["receipt"], interest_earned=inflow["interest"], other_adjustments=inflow["other"],
		total_expenditure=flt(sum(h.spent_in_period for h in heads), 2),
		unreconciled_amount=flt(sum(row.amount for row in unreconciled), 2),
		heads=heads, unreconciled=unreconciled,
	)  # fmt: skip
	figures.total_available = flt(figures.opening_unspent + sum(inflow.values()), 2)
	figures.closing_unspent = flt(figures.total_available - figures.total_expenditure, 2)
	return figures


def liability_inflows(sanction, from_date, to_date, lock=False):
	"""({kind: amount} before the period, {kind: amount} in it): credit less debit on the liability by kind, without
	the Grant Income Recognition entries."""
	kinds = {}
	for doctype, kind in (("Grant Receipt", "receipt"), ("Grant Interest", "interest")):
		for entry in frappe.get_all(doctype, {"sanction": sanction.name, "journal_entry": ["is", "set"]}, pluck="journal_entry"):
			kinds[entry] = kind
	recognitions = set(frappe.get_all("Grant Income Recognition", {"company": sanction.company, "journal_entry": ["is", "set"]}, pluck="journal_entry"))
	gl = frappe.qb.DocType("GL Entry")
	query = (
		frappe.qb.from_(gl)
		.select(gl.voucher_no, gl.posting_date, Sum(gl.credit - gl.debit))
		.where((gl.account == sanction.liability_account) & (gl.is_cancelled == 0) & (gl.posting_date <= to_date))
		.groupby(gl.voucher_no, gl.posting_date)
	)  # fmt: skip
	before, during = dict.fromkeys(("receipt", "interest", "other"), 0), dict.fromkeys(("receipt", "interest", "other"), 0)
	for voucher, posting_date, amount in (query.for_update() if lock else query).run():
		if voucher in recognitions:
			continue
		bucket = before if getdate(posting_date) < getdate(from_date) else during
		bucket[kinds.get(voucher, "other")] += flt(amount)
	return {k: flt(v, 2) for k, v in before.items()}, {k: flt(v, 2) for k, v in during.items()}


def sanction_heads(sanction):
	"""[(head, is_capital, sanctioned amount)] in sanction order; throws when two heads share an account (the GL could
	not be split between them)."""
	heads = {}
	for row in frappe.get_all(
		"Sanction Head", {"parent": sanction.name, "parenttype": "Sanction"}, ["budget_head", "is_capital", "amount"], order_by="idx"
	):
		head = heads.setdefault(row.budget_head, frappe._dict(is_capital=row.is_capital, amount=0))
		head.amount += flt(row.amount)
	owner = {}
	for head in heads:
		heads[head].accounts = set(head_accounts(head, sanction.company))
		for account in heads[head].accounts:
			if account in owner:
				frappe.throw(
					_("Budget heads {0} and {1} of Sanction {2} share account {3}: the ledger can't be split between them.").format(
						owner[account], head, sanction.name, account
					)
				)
			owner[account] = head
	return heads


def head_figures(sanction, before, to_date, lock=False):
	rows = []
	for head, values in sanction_heads(sanction).items():
		spent_before = posted(sanction.cost_center, values.accounts, before, lock)
		spent_to_date = posted(sanction.cost_center, values.accounts, to_date, lock)
		rows.append(
			frappe._dict(
				budget_head=head, is_capital=values.is_capital, sanctioned_amount=flt(values.amount, 2),
				spent_before=flt(spent_before, 2), spent_in_period=flt(spent_to_date - spent_before, 2),
				spent_to_date=flt(spent_to_date, 2), balance=flt(values.amount - spent_to_date, 2),
			)  # fmt: skip
		)
	return rows


def unreconciled_entries(sanction, to_date, lock=False):
	"""[{voucher_type, voucher_no, account, amount}] of spending on the sanction's project or cost centre up to
	`to_date` that is not on one of its head accounts on its cost centre."""
	accounts = set()
	for values in sanction_heads(sanction).values():
		accounts |= values.accounts
	gl, account = frappe.qb.DocType("GL Entry"), frappe.qb.DocType("Account")
	spending = (account.account_type == "Fixed Asset") | (
		(account.root_type == "Expense") & Coalesce(account.account_type, "").notin(NON_SPENDING_EXPENSE_TYPES)
	)
	on_heads = gl.cost_center == sanction.cost_center
	if accounts:
		on_heads = on_heads & gl.account.isin(list(accounts))
	else:
		on_heads = on_heads & (gl.account == "")
	query = (
		frappe.qb.from_(gl).join(account).on(account.name == gl.account)
		.select(gl.voucher_type, gl.voucher_no, gl.account, Sum(gl.debit - gl.credit).as_("amount"))
		.where(
			(gl.company == sanction.company) & (gl.is_cancelled == 0) & (gl.posting_date <= to_date)
			& ((gl.cost_center == sanction.cost_center) | (gl.project == sanction.project))
			& spending & ~on_heads
		)
		.groupby(gl.voucher_type, gl.voucher_no, gl.account)
		.orderby(gl.voucher_no)
	)  # fmt: skip
	rows = (query.for_update() if lock else query).run(as_dict=True)
	return [row for row in rows if flt(row.amount, 2)]


# snapshot and source changed
def signature(figures):
	"""The figures an approval stands behind, comparable after a JSON round trip."""
	return json.loads(
		json.dumps(
			{
				"figures": {field: flt(figures.get(field), 2) for field in FIGURE_FIELDS},
				"heads": [
					{"budget_head": row.get("budget_head"), "is_capital": int(row.get("is_capital") or 0)}
					| {field: flt(row.get(field), 2) for field in HEAD_FIELDS[2:]}
					for row in figures.get("heads") or []
				],
			},
			default=str,
		)
	)


def snapshot(figures):
	return json.dumps({**signature(figures), "computed_at": str(now_datetime()), "engine_version": ENGINE_VERSION}, indent=1)


def source_moved(uc):
	"""True when the ledger behind an approved UC no longer gives its snapshot figures."""
	stored = json.loads(uc.snapshot or "{}")
	current = signature(utilisation_figures(uc.sanction, uc.from_date, uc.to_date))
	return {"figures": stored.get("figures"), "heads": stored.get("heads")} != current


def note_ledger_change(doc, method=None):
	"""on_submit of GL Entry (postings and the reversing entries of a cancel): recheck the approved UCs the entry can
	move, those of its liability, cost centre or project with a period end on or after its date."""
	uc = frappe.qb.DocType(UC_DOCTYPE)
	touches = uc.liability_account == doc.account
	if doc.cost_center:
		touches = touches | (uc.cost_center == doc.cost_center)
	if doc.project:
		touches = touches | (uc.project == doc.project)
	names = (
		frappe.qb.from_(uc).select(uc.name)
		.where((uc.docstatus == 1) & (uc.source_changed == 0) & (uc.to_date >= doc.posting_date) & touches)
		.run(pluck=True)
	)  # fmt: skip
	for name in names:
		uc = frappe.get_doc(UC_DOCTYPE, name)
		try:
			changed = source_moved(uc)
		except frappe.ValidationError:  # e.g. a head mapping changed since: never block the posting, flag the UC
			frappe.clear_last_message()
			changed = True
		mark_source(uc, changed)


def mark_source(uc, changed=None):
	"""Set the UC's source-changed flag from a recompute (or `changed` when given); returns the flag."""
	if changed is None:
		changed = source_moved(uc)
	if bool(changed) != bool(uc.source_changed):
		uc.db_set({"source_changed": int(changed), "source_changed_on": now_datetime() if changed else None}, notify=True)
	return bool(changed)


# access: the PI reads the UCs of their sanctions
STAFF_ROLES = {"System Manager", "Accounts Manager", "Accounts User", "Principal"}


def is_staff(user):
	return user == "Administrator" or bool(STAFF_ROLES & set(frappe.get_roles(user)))


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if is_staff(user):
		return True
	return ptype in ("read", "print") and doc.pi_user == user


def permission_query(user=None):
	user = user or frappe.session.user
	if is_staff(user):
		return ""
	return f"`tab{UC_DOCTYPE}`.pi_user = {frappe.db.escape(user)}"
