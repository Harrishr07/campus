"""M07-01 Faculty Norm: AICTE/UGC qualification by cadre, cadre ratio and student-faculty ratio for a company,
versioned by Effective From (campus.faculty.norms resolves the version in force). One version per company and date:
the name is company + date, so the primary key enforces it."""

import frappe
from frappe import _
from frappe.model.document import Document


class FacultyNorm(Document):
	def autoname(self):
		self.name = f"{self.company} - {self.effective_from}"

	def validate(self):
		cadres = [row.cadre for row in self.cadres]
		duplicates = sorted({c for c in cadres if cadres.count(c) > 1})
		if duplicates:
			frappe.throw(_("Each cadre can appear once; repeated: {0}").format(", ".join(duplicates)))
