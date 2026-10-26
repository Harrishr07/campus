"""M04-01 Seat Matrix: one per company, program and academic year; the rows are computed (see admissions.seat_matrix)."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.admissions import seat_matrix


class SeatMatrix(Document):
	def validate(self):
		company = frappe.db.get_value("Program", self.program, "oc_company")
		if company != self.company:
			frappe.throw(
				_("Program {0} belongs to {1}, not {2}.").format(self.program, company, self.company)
			)
		self.matrix_key = seat_matrix.matrix_key(self.company, self.program, self.academic_year)
		if frappe.db.exists("Seat Matrix", {"matrix_key": self.matrix_key, "name": ("!=", self.name)}):
			frappe.throw(
				_("A Seat Matrix already exists for {0}, {1}, {2}.").format(
					self.company, self.program, self.academic_year
				)
			)
		seat_matrix.prepare_rows(self, recount=bool(self.flags.recount))
