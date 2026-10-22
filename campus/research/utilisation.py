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
period end queues it for a recompute just before the transaction commits (once per UC, with every row of the voucher
posted), and a difference marks it "source changed"; the approved figures stay as they were."""

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
RECHECK_FLAG = "campus_uc_recheck"
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
	heads_by_name = sanction_heads(sanction)
	heads = head_figures(sanction, heads_by_name, before, to_date, lock)
	unreconciled = unreconciled_entries(sanction, heads_by_name, to_date, lock)
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
	recognitions = recognition_entries(sanction.name)
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


def recognition_entries(sanction):
	"""Journal Entries of the Grant Income Recognitions that included `sanction`."""
	row, doc = frappe.qb.DocType("Grant Income Recognition Sanction"), frappe.qb.DocType("Grant Income Recognition")
	return set(
		frappe.qb.from_(doc).join(row).on(row.parent == doc.name)
		.select(doc.journal_entry)
		.where((row.sanction == sanction) & (row.parenttype == "Grant Income Recognition") & doc.journal_entry.isnotnull())
		.run(pluck=True)
	)  # fmt: skip


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


def head_figures(sanction, heads, before, to_date, lock=False):
	rows = []
	for head, values in heads.items():
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


def unreconciled_entries(sanction, heads, to_date, lock=False):
	"""[{voucher_type, voucher_no, account, amount}] of spending on the sanction's project or cost centre up to
	`to_date` that is not on one of its head accounts on its cost centre.

	Two reads: on the cost centre (indexed, locked when `lock`), and on the project under any other cost centre. GL
	Entry has no index on project, so that read is never a locking one: it would lock most of the college's ledger."""
	accounts = set()
	for values in heads.values():
		accounts |= values.accounts
	gl = frappe.qb.DocType("GL Entry")
	on_cost_center = gl.cost_center == sanction.cost_center
	off_heads = ~gl.account.isin(list(accounts)) if accounts else gl.account.isnotnull()
	locked = unreconciled_query(sanction, to_date, on_cost_center & off_heads)
	elsewhere = unreconciled_query(
		sanction, to_date, (gl.project == sanction.project) & (gl.cost_center.isnull() | (gl.cost_center != sanction.cost_center))
	)
	totals = {}
	for row in (locked.for_update() if lock else locked).run(as_dict=True) + elsewhere.run(as_dict=True):
		key = (row.voucher_type, row.voucher_no, row.account)
		totals[key] = totals.get(key, 0) + flt(row.amount)
	return [
		frappe._dict(voucher_type=key[0], voucher_no=key[1], account=key[2], amount=amount)
		for key, amount in sorted(totals.items(), key=lambda item: item[0][1])
		if flt(amount, 2)
	]


def unreconciled_query(sanction, to_date, condition):
	gl, account = frappe.qb.DocType("GL Entry"), frappe.qb.DocType("Account")
	spending = (account.account_type == "Fixed Asset") | (
		(account.root_type == "Expense") & Coalesce(account.account_type, "").notin(NON_SPENDING_EXPENSE_TYPES)
	)
	return (
		frappe.qb.from_(gl).join(account).on(account.name == gl.account)
		.select(gl.voucher_type, gl.voucher_no, gl.account, Sum(gl.debit - gl.credit).as_("amount"))
		.where((gl.company == sanction.company) & (gl.is_cancelled == 0) & (gl.posting_date <= to_date) & spending & condition)
		.groupby(gl.voucher_type, gl.voucher_no, gl.account)
	)  # fmt: skip


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


def source_moved(uc, lock=False):
	"""True when the ledger behind an approved UC no longer gives its snapshot figures (read with locking reads when
	`lock`, by a caller holding the sanction lock)."""
	stored = json.loads(uc.snapshot or "{}")
	current = signature(utilisation_figures(uc.sanction, uc.from_date, uc.to_date, lock=lock))
	return {"figures": stored.get("figures"), "heads": stored.get("heads")} != current


def note_ledger_change(doc, method=None):
	"""on_submit of GL Entry (postings and the reversing entries of a cancel): queue the approved UCs the entry can
	move, those of its liability, cost centre or project with a period end on or after its date. They are rechecked
	once, just before the transaction commits: the voucher's other rows aren't posted yet when its first row is, so a
	voucher that nets to zero (or a Grant Income Recognition, linked to its entry only afterwards) would flag wrongly."""
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
	if names:
		queue_recheck(names)


def queue_recheck(names):
	queued = frappe.flags.get(RECHECK_FLAG)
	if queued is None:  # first in this transaction
		queued = frappe.flags[RECHECK_FLAG] = set()
		frappe.db.before_commit.add(recheck_queued)
		frappe.db.after_rollback.add(forget_queued)
	queued.update(names)


def forget_queued():
	frappe.flags.pop(RECHECK_FLAG, None)


def recheck_queued():
	"""before_commit: recheck each queued UC once against the transaction's whole ledger. A failing UC is logged and
	skipped, so the commit (and the posting) goes ahead; only a deadlock is raised, for the request to be retried."""
	for name in sorted(frappe.flags.pop(RECHECK_FLAG, None) or ()):
		try:
			uc = frappe.db.get_value(UC_DOCTYPE, name, ["docstatus", "source_changed"], as_dict=True)
			if uc and uc.docstatus == 1 and not uc.source_changed:
				recheck(frappe.get_doc(UC_DOCTYPE, name))
		except Exception as error:
			if frappe.db.is_deadlocked(error):
				raise
			frappe.clear_last_message()
			log_recheck_failure(name, error, _("it could not be rechecked"))


def recheck(uc):
	try:
		changed = source_moved(uc)
	except Exception as error:  # a head mapping changed since, a corrupt snapshot...: never block the posting
		if frappe.db.is_deadlocked(error):
			raise
		frappe.clear_last_message()
		log_recheck_failure(uc.name, error, _("it is marked Source Changed"))
		changed = True
	mark_source(uc, changed)


def log_recheck_failure(name, error, outcome):
	frappe.log_error(
		title=_("Utilisation Certificate recheck failed"),
		message=_("{0} could not be recomputed after a ledger change ({1}); {2}.").format(name, type(error).__name__, outcome),
		reference_doctype=UC_DOCTYPE, reference_name=name,
	)  # fmt: skip


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
