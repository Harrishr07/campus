"""M05-05 Fee concessions: an approved Fee Concession becomes a discount on the matching line of the student's next fee invoice.

A concession names a fee category that is configured as concession-eligible (Fee Category.oc_concession_allowed),
a percent or an amount, and an academic year. When a Sales Invoice for the student is validated as a draft, each open
concession whose year covers the posting date discounts one line of its fee category (the line is tagged with the
concession). Concessions are of the student's own company (Fee Concession.company = student.oc_company), so a trust-raised hostel or
mess invoice cannot take one; that needs a shared-service rule later. Submitting the invoice re-reads the concession under
its lock (live, same student and company, still open) and marks the concession Applied under the
concession's row lock, so one concession discounts one invoice; cancelling the invoice releases it.
"""

import frappe
from frappe import _
from frappe.utils import flt

from campus.campus_finance.invoices import is_opening

OPEN, APPLIED = "Open", "Applied"
PERCENT = "Percent"
CENT = 0.005


def concession_discount(base, concession_type, percent, amount):
	"""The discount on `base`: a percent of it or a fixed amount, never more than `base`."""
	value = flt(base) * flt(percent) / 100 if concession_type == PERCENT else flt(amount)
	return flt(min(max(value, 0), flt(base)), 2)


def open_concessions(student, company, posting_date):
	"""Approved, not yet applied concessions of the student whose academic year covers `posting_date`."""
	concession, year = frappe.qb.DocType("Fee Concession"), frappe.qb.DocType("Academic Year")
	return (
		frappe.qb.from_(concession)
		.join(year)
		.on(year.name == concession.academic_year)
		.select(concession.name, concession.fee_category, concession.concession_type, concession.percent, concession.amount)
		.where(concession.docstatus == 1)
		.where(concession.status == OPEN)
		.where(concession.student == student)
		.where(concession.company == company)
		.where(year.year_start_date <= posting_date)
		.where(year.year_end_date >= posting_date)
		.orderby(concession.creation)
		.run(as_dict=True)
	)


def live_for_invoice(name, doc):
	"""Whether concession `name` may discount `doc`: submitted, and either open or already consumed by this invoice,
	and of the invoice's student and company."""
	found = frappe.db.get_value("Fee Concession", name, ["docstatus", "status", "applied_invoice", "student", "company"], as_dict=True)
	return bool(
		found and found.docstatus == 1 and (found.student, found.company) == (doc.get("student"), doc.company)
		and (found.status == OPEN or found.applied_invoice == doc.name)
	)


def strip_stale_tags(doc):
	"""Remove the tag and discount from lines whose concession can no longer discount this invoice."""
	for row in doc.items:
		name = row.get("oc_fee_concession")
		if name and not live_for_invoice(name, doc):
			row.oc_fee_concession = None
			row.discount_amount = 0
			row.rate = flt(row.price_list_rate) or flt(row.rate)


def apply_to_invoice(doc, method=None):
	"""Doc event (Sales Invoice before_validate): discount the fee line of each open concession of the student.

	Credit notes and opening balances (legacy dues brought forward) take none. One concession discounts one line (ERPNext's own line discount, so the invoice shows price list rate, discount
	and rate); a concession with no untouched line of its category waits for the next invoice. Lines tagged with a
	concession that is no longer usable (cancelled, used by another invoice, another student's) are cleaned first."""
	if doc.is_return or is_opening(doc) or not doc.get("student") or doc.docstatus > 1:
		return  # a credit note or an opening balance brought forward is not a fee invoice
	if not doc.is_new() and frappe.db.get_value(doc.doctype, doc.name, "docstatus") != 0:
		return  # an invoice already submitted is not touched (this event also runs while submitting a draft)
	strip_stale_tags(doc)
	if doc.docstatus != 0:
		return
	tagged = {row.get("oc_fee_concession") for row in doc.items}
	for concession in open_concessions(doc.student, doc.company, doc.posting_date):
		if concession.name in tagged:
			continue
		category = frappe.db.get_value("Fee Category", concession.fee_category, ["item", "oc_concession_allowed"], as_dict=True)
		if not category.oc_concession_allowed:
			continue
		item = category.item
		line = next((r for r in doc.items if r.item_code == item and not r.get("oc_fee_concession") and flt(r.rate) > 0), None)
		if not line:
			continue
		unit = flt(line.price_list_rate) or flt(line.rate)
		discount = concession_discount(unit * flt(line.qty), concession.concession_type, concession.percent, concession.amount)
		if discount <= 0:
			continue
		line.price_list_rate = unit
		line.discount_amount = flt(discount / flt(line.qty), line.precision("discount_amount"))
		line.rate = flt(unit - line.discount_amount, line.precision("rate"))
		line.oc_fee_concession = concession.name


def mark_applied(doc, method=None):
	"""Doc event (Sales Invoice on_submit): the concessions on the invoice are consumed, once."""
	for row in doc.items:
		name = row.get("oc_fee_concession")
		if not name:
			continue
		found = frappe.db.get_value(
			"Fee Concession", name, ["docstatus", "status", "applied_invoice", "student", "company"], as_dict=True, for_update=True
		)  # re-read under the lock: the tag on the line is only a claim
		if not (found and found.docstatus == 1 and (found.student, found.company) == (doc.get("student"), doc.company)):
			frappe.throw(_("Fee Concession {0} cannot discount this invoice.").format(name))
		if found.status != OPEN and found.applied_invoice != doc.name:
			frappe.throw(_("Fee Concession {0} is already applied to {1}.").format(name, found.applied_invoice))
		frappe.db.set_value(
			"Fee Concession", name, {"status": APPLIED, "applied_invoice": doc.name, "discount_amount": flt(row.discount_amount) * flt(row.qty)}, update_modified=False
		)


def release(doc, method=None):
	"""Doc event (Sales Invoice on_cancel): a cancelled invoice gives its concessions back."""
	for name in {row.get("oc_fee_concession") for row in doc.items if row.get("oc_fee_concession")}:
		if frappe.db.get_value("Fee Concession", name, "applied_invoice", for_update=True) == doc.name:
			frappe.db.set_value(
				"Fee Concession", name, {"status": OPEN, "applied_invoice": None, "discount_amount": 0}, update_modified=False
			)


def clear_draft_tags(concession, method=None):
	"""Doc event (Fee Concession on_cancel): draft invoices carrying the concession lose the tag and the discount
	(Frappe would refuse to save them with a link to a cancelled document); saving them recalculates the totals."""
	item, parent = frappe.qb.DocType("Sales Invoice Item"), frappe.qb.DocType("Sales Invoice")
	drafts = (
		frappe.qb.from_(item).join(parent).on(parent.name == item.parent).select(item.name)
		.where(item.oc_fee_concession == concession.name).where(parent.docstatus == 0).run(pluck=True)
	)  # fmt: skip
	if drafts:
		frappe.db.sql(
			"update `tabSales Invoice Item` set oc_fee_concession = null, discount_amount = 0, rate = price_list_rate where name in %s",
			(drafts,),
		)
