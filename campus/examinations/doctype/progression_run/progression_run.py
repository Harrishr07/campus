"""M05-03 Progression Run: term-end promote / detain / probation of a programme's students by their regulation's
Progression Rule. Submitting queues the bulk run (campus.examinations.progression); its outcomes fill the table."""

import frappe
from frappe import _
from frappe.model.document import Document


class ProgressionRun(Document):
	def validate(self):
		if frappe.db.get_value("Program", self.program, "oc_company") != self.company:
			frappe.throw(
				_("Program {0} does not belong to {1}.").format(
					frappe.bold(self.program), frappe.bold(self.company)
				)
			)

	def on_submit(self):
		from campus.examinations import progression

		self.db_set("bulk_run", progression.start(self))
