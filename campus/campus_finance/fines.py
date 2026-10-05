"""M09-01 Late fines: Fine Rule slabs, the pure fine calculation and the Daily Fine Run.

Fine calculation (pure functions, no database)
- late days = days past the due date minus the rule's grace days.
- a slab is crossed once late days reach its `from_day`; every crossed slab is charged exactly once.
- a plain slab charges its fixed amount, or its percent of the invoice's outstanding amount on the day the
  slab is charged. A per-day slab charges that amount or percent for every day of the slab
  (`to_day - from_day + 1`), i.e. the whole slab is levied when it is crossed.

The Daily Fine Run creates one fine Sales Invoice per (overdue invoice, slab). Idempotency is the primary key
of Fine Applied, whose name is "<invoice>::<slab row name>", inserted in the same transaction as the fine invoice.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, nowdate

from campus.campus_finance.doctype.fine_applied.fine_applied import key as applied_key
from campus.campus_finance.fee_heads import FINE, category_for_type
from campus.campus_platform.bulk import run_bulk

HANDLER = "campus.campus_finance.fines.apply_fine"
KEY = "campus.campus_finance.fines.item_key"
RUN_TYPE = "Daily Fine Run"


def late_days(due_date, as_of, grace_days):
	"""Days late after the grace period; never negative."""
	return max(date_diff(getdate(as_of), getdate(due_date)) - (grace_days or 0), 0)


def slabs_crossed(days_late, slabs):
	"""The slabs reached after `days_late` late days, in order. Each slab needs `from_day` and `to_day`."""
	return sorted((s for s in slabs if s.from_day <= days_late), key=lambda s: s.from_day)


def slab_amount(slab, outstanding):
	"""The fine one slab levies on an invoice with the given outstanding amount."""
	days = (slab.to_day - slab.from_day + 1) if slab.per_day else 1
	rate = flt(slab.amount) if flt(slab.amount) else flt(outstanding) * flt(slab.percent) / 100
	return flt(rate * days, 2)


def validate_rule(rule):
	rows = sorted(rule.slabs, key=lambda s: s.from_day)
	for slab in rows:
		if slab.from_day < 1 or (slab.to_day and slab.to_day < slab.from_day):
			frappe.throw(_("Row {0}: the day range is not valid.").format(slab.idx))
		if bool(flt(slab.amount)) == bool(flt(slab.percent)) or flt(slab.amount) < 0 or not 0 <= flt(slab.percent) <= 100:
			frappe.throw(_("Row {0}: enter either an amount or a percent (0-100).").format(slab.idx))
		if slab.per_day and not slab.to_day:
			frappe.throw(_("Row {0}: a per-day slab needs a To Day.").format(slab.idx))
	for before, after in zip(rows, rows[1:]):
		if not before.to_day or before.to_day >= after.from_day:
			frappe.throw(_("Row {0}: the day range overlaps the previous slab.").format(after.idx))
	if rule.enabled and frappe.db.exists(
		"Fine Rule",
		{"company": rule.company, "fee_category": rule.fee_category or ("is", "not set"), "enabled": 1, "name": ("!=", rule.name)},
	):
		frappe.throw(_("An enabled Fine Rule already exists for this company and fee."))


def rule_for(invoice, rules):
	"""The most specific enabled rule for the invoice: one naming a fee on its items, else the all-fees rule."""
	items = invoice.item_codes
	by_category = [r for r in rules if r.fee_category and r.fee_category in items]
	return (by_category or [r for r in rules if not r.fee_category] or [None])[0]


def daily_fine_run(as_of=None):
	"""Scheduled entry point: queue one bulk run applying every newly due fine; returns the Bulk Run or None."""
	as_of = str(getdate(as_of or nowdate()))
	items = fine_items(as_of)
	if items:
		return run_bulk(RUN_TYPE, items, HANDLER, key=KEY, parameters={"as_of": as_of})


def item_key(item):
	return applied_key(item["invoice"], item["slab"])


def fine_items(as_of):
	"""[{invoice, slab, rule}] for every overdue, unpaid student invoice and slab not yet fined."""
	rules = frappe.get_all("Fine Rule", {"enabled": 1}, ["name", "company", "fee_category", "grace_days"])
	if not rules:
		return []
	done = set(frappe.get_all("Fine Applied", pluck="name", limit=0))
	items = []
	for invoice in overdue_invoices(as_of, {r.company for r in rules}):
		rule = rule_for(invoice, [r for r in rules if r.company == invoice.company])
		if not rule:
			continue
		slabs = frappe.get_all("Fine Rule Slab", {"parent": rule.name}, ["name", "from_day", "to_day", "amount", "percent", "per_day"])
		for slab in slabs_crossed(late_days(invoice.due_date, as_of, rule.grace_days), slabs):
			if applied_key(invoice.name, slab.name) not in done:
				items.append({"invoice": invoice.name, "slab": slab.name, "rule": rule.name})
	return items


def overdue_invoices(as_of, companies):
	fines = frappe.get_all("Fine Applied", pluck="fine_invoice", limit=0)
	invoices = frappe.get_all(
		"Sales Invoice",
		{
			"docstatus": 1, "student": ("is", "set"), "outstanding_amount": (">", 0), "due_date": ("<", as_of),
			"company": ("in", list(companies)), "is_return": 0, "name": ("not in", fines or [""]),
		},
		["name", "company", "due_date"],
		limit=0,
	)
	items = frappe.get_all(
		"Sales Invoice Item", {"parent": ("in", [i.name for i in invoices] or [""])}, ["parent", "item_code"], limit=0
	)
	for invoice in invoices:
		invoice.item_codes = {i.item_code for i in items if i.parent == invoice.name}
	return invoices


def apply_fine(item, run):
	"""Bulk handler: record the (invoice, slab) fine and create its fine invoice. DB-only, no commit."""
	as_of = run.get_parameters()["as_of"]
	invoice = frappe.get_doc("Sales Invoice", item["invoice"])
	slab = frappe.get_doc("Fine Rule Slab", item["slab"])
	if invoice.docstatus != 1 or not flt(invoice.outstanding_amount):
		return  # settled since the run was queued
	amount = slab_amount(slab, invoice.outstanding_amount)
	applied = frappe.get_doc(
		{
			"doctype": "Fine Applied", "sales_invoice": invoice.name, "slab_key": slab.name, "fine_rule": item["rule"],
			"company": invoice.company, "amount": amount, "applied_on": as_of,
		}
	)
	try:
		applied.insert(ignore_permissions=True)  # the primary key refuses a second fine for the same (invoice, slab)
	except frappe.DuplicateEntryError:
		return
	applied.db_set("fine_invoice", make_fine_invoice(invoice, amount, slab, as_of).name)


def make_fine_invoice(invoice, amount, slab, as_of):
	category = category_for_type(FINE)
	fine = frappe.get_doc(
		{
			"doctype": "Sales Invoice", "company": invoice.company, "customer": invoice.customer, "student": invoice.student,
			"posting_date": as_of, "set_posting_time": 1, "due_date": as_of,
			"remarks": _("Late fine for {0}, from day {1}").format(invoice.name, slab.from_day),
			"items": [{"item_code": category, "qty": 1, "rate": amount}],
		}
	)
	fine.insert(ignore_permissions=True)
	fine.submit()
	return fine
