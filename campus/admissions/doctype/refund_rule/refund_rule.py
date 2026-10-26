"""M04-04 Refund Rule: day-window slabs giving the deduction (percent or fixed processing fee) on cancellation."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class RefundRule(Document):
	def validate(self):
		previous_end = None
		for slab in sorted(self.slabs, key=lambda s: s.days_from_admission_start):
			if (
				slab.days_to_admission_start < slab.days_from_admission_start
				or slab.days_from_admission_start < 0
			):
				frappe.throw(_("Row {0}: the day window is not valid.").format(slab.idx))
			if not 0 <= flt(slab.deduction_percent) <= 100 or flt(slab.processing_fee) < 0:
				frappe.throw(
					_("Row {0}: deduction must be 0-100% and the fee cannot be negative.").format(slab.idx)
				)
			if previous_end is not None and slab.days_from_admission_start <= previous_end:
				frappe.throw(_("Row {0}: the day window overlaps another slab.").format(slab.idx))
			previous_end = slab.days_to_admission_start
