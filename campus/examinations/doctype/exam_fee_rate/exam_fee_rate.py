"""M06-01 Exam Fee Rate: the exam fee per registered course and the late fee slabs, per company (and program).

A rate naming the program beats the company's blank-program rate. Slabs count days after the Exam Session's
registration closing date, both bounds inclusive, and must not overlap.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class ExamFeeRate(Document):
	def validate(self):
		clash = {
			"company": self.company,
			"program": self.program or ["is", "not set"],
			"name": ["!=", self.name],
		}
		if frappe.db.exists(self.doctype, clash):
			frappe.throw(
				_("An Exam Fee Rate already exists for {0} {1}.").format(
					self.company, self.program or _("(all programs)")
				)
			)
		self.validate_slabs()

	def validate_slabs(self):
		slabs = sorted(self.late_fee_slabs, key=lambda s: s.from_day)
		for slab in slabs:
			if slab.from_day < 1 or slab.to_day < slab.from_day:
				frappe.throw(
					_("Row {0}: a slab runs from day 1 or later up to a day not before it.").format(slab.idx)
				)
		for earlier, later in zip(slabs, slabs[1:]):
			if later.from_day <= earlier.to_day:
				frappe.throw(_("Late fee slabs in rows {0} and {1} overlap.").format(earlier.idx, later.idx))
