"""M04-02 Allotment Import: a counselling authority's allotment file applied to Student Applicants."""

import frappe
from frappe import _
from frappe.model.document import Document


class AllotmentImport(Document):
	def validate(self):
		if not frappe.db.get_value("Counselling Authority", self.counselling_authority, "enabled"):
			frappe.throw(_("Counselling Authority {0} is disabled.").format(self.counselling_authority))
		seen = set()
		for row in self.program_mapping:
			code = row.source_code.strip().lower()
			if code in seen:
				frappe.throw(_("Row {0}: branch code {1} is mapped twice.").format(row.idx, row.source_code))
			seen.add(code)
			company = frappe.db.get_value("Program", row.program, "oc_company")
			if company != self.company:
				frappe.throw(
					_("Row {0}: program {1} belongs to {2}, not {3}.").format(
						row.idx, row.program, company, self.company
					)
				)
