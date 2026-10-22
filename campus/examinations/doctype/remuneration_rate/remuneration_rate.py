"""M06-04 Remuneration Rate: what an examination activity pays per unit (script valued, paper set or scrutinised,
invigilation duty) in a college, versioned by Effective From (one per activity, college and date, by its name). A claim
line takes the version in force on its work date (campus.examinations.remuneration)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class RemunerationRate(Document):
	def validate(self):
		if flt(self.rate) <= 0:
			frappe.throw(_("The rate must be more than zero."))
