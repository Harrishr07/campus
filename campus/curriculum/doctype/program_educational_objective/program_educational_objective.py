"""M03-02 Program Educational Objective of a programme under a regulation, with its PEO-Mission mapping."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.curriculum.outcomes import check_programme_regulation, normalise_code


class ProgramEducationalObjective(Document):
	def autoname(self):
		self.peo_code = normalise_code(self.peo_code)
		self.name = f"{self.program}-{self.regulation}-{self.peo_code}"

	def validate(self):
		check_programme_regulation(self.program, self.regulation)
		self.validate_missions()

	def validate_missions(self):
		department = frappe.db.get_value("Program", self.program, "department")
		seen = set()
		for row in self.mission_mappings:
			if row.mission in seen:
				frappe.throw(_("Row {0}: mission {1} is mapped twice.").format(row.idx, frappe.bold(row.mission)))
			seen.add(row.mission)
			if frappe.db.get_value("Department Mission", row.mission, "department") != department:
				frappe.throw(
					_("Row {0}: {1} is not a mission of {2}, the department of {3}.").format(
						row.idx, frappe.bold(row.mission), frappe.bold(department or _("(none)")), frappe.bold(self.program)
					)
				)
