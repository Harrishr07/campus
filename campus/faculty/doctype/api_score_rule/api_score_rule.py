"""M07-05 API Score Rule: activity -> points with annual caps and the KRA weightages, versioned by Effective From
(campus.faculty.self_appraisal.rule_in_force resolves the version in force). One version per company and date: the name is
company + date, so the primary key enforces it. Points, caps and targets are records, never constants."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class APIScoreRule(Document):
	def autoname(self):
		self.name = f"{self.company} - {self.effective_from}"

	def validate(self):
		self.check_rows()
		self.check_kras()

	def check_rows(self):
		activities = [row.activity for row in self.rows]
		repeated = sorted({a for a in activities if activities.count(a) > 1})
		if repeated:
			frappe.throw(_("Each activity can appear once; repeated: {0}").format(", ".join(repeated)))
		kras = {row.kra for row in self.kras}
		for row in self.rows:
			if row.kra not in kras:
				frappe.throw(_("Row {0}: KRA {1} is not in the KRAs table.").format(row.idx, row.kra))

	def check_kras(self):
		kras = [row.kra for row in self.kras]
		repeated = sorted({k for k in kras if kras.count(k) > 1})
		if repeated:
			frappe.throw(_("Each KRA can appear once; repeated: {0}").format(", ".join(repeated)))
		total = sum(flt(row.weightage) for row in self.kras)
		if flt(total, 2) != 100:
			frappe.throw(_("The KRA weightages must add up to 100. Currently {0}.").format(total))
