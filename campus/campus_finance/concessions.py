"""M05-05 Fee concessions: an approved Fee Concession becomes a discount on the matching line of the student's next fee invoice.

A concession names a fee category that is configured as concession-eligible (Fee Category.oc_concession_allowed),
a percent or an amount, and an academic year. When a Sales Invoice for the student is validated as a draft, each open
concession whose year covers the posting date discounts one line of its fee category (the line is tagged with the
concession). Submitting the invoice marks the concession Applied under the
concession's row lock, so one concession discounts one invoice; cancelling the invoice releases it.
"""

import frappe
from frappe import _
from frappe.utils import flt

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


def apply_to_invoice(doc, method=None):
	"""Doc event (Sales Invoice before_validate): discount the fee line of each open concession of the student.

	One concession discounts one line (ERPNext's own line discount, so the invoice shows price list rate, discount
	and rate); a concession with no untouched line of its category waits for the next invoice."""
	if doc.docstatus != 0 or doc.is_return or not doc.get("student"):
		return
	tagged = {row.get("oc_fee_concession") for row in doc.items}
	for concession in open_concessions(doc.student, doc.company, doc.posting_date):
		if concession.name in tagged:
			continue
		item = frappe.db.get_value("Fee Category", concession.fee_category, "item")
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
		status, invoice = frappe.db.get_value("Fee Concession", name, ["status", "applied_invoice"], for_update=True)
		if status != OPEN and invoice != doc.name:
			frappe.throw(_("Fee Concession {0} is already applied to {1}.").format(name, invoice))
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
