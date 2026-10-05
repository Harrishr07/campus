"""M04-04 Refund by Refund Rule slab. `refund_for` is a pure function; the lookups are kept apart."""

import frappe
from frappe import _
from frappe.utils import date_diff, flt


def days_since_start(start, on_date):
	"""Whole days from the admission start to `on_date`; a cancellation before the start counts as day 0."""
	return max(date_diff(on_date, start), 0)


def slab_for(slabs, days):
	"""The slab whose day window holds `days`, or None (after the last slab nothing is refunded)."""
	for slab in slabs:
		if slab.days_from_admission_start <= days <= slab.days_to_admission_start:
			return slab


def refund_for(slabs, days, amount):
	"""{"slab", "deduction", "refundable"} for `amount` paid or invoiced, cancelled on day `days`.

	The slab deducts `deduction_percent` of the amount plus its fixed `processing_fee` (either may be zero),
	never more than the amount. With no slab covering the day the whole amount is deducted.
	"""
	amount = flt(amount)
	slab = slab_for(slabs, days)
	if not slab:
		return {"slab": None, "deduction": amount, "refundable": 0.0}
	deduction = min(amount * flt(slab.deduction_percent) / 100 + flt(slab.processing_fee), amount)
	deduction = flt(deduction, 2)
	return {"slab": slab, "deduction": deduction, "refundable": flt(amount - deduction, 2)}


def find_refund_rule(company, academic_year):
	"""The Refund Rule of the company for the admission year, else the company's rule without a year (latest wins)."""
	for year in (academic_year, None):
		filters = {"company": company, "admission_year": year if year else ("is", "not set")}
		name = frappe.db.get_value("Refund Rule", filters, "name", order_by="creation desc")
		if name:
			return frappe.get_doc("Refund Rule", name)
	frappe.throw(_("No Refund Rule for {0}.").format(company))
