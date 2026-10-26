"""M03-03 PO Attainment Run: PO / PSO attainment of a programme batch (optionally one academic year) from its submitted
CO Attainment Runs and the programme exit survey, under the batch regulation's Attainment Policy (computed by the bulk
runner, campus.curriculum.attainment); one live run per programme, batch and year, submitted once computed."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.curriculum import attainment


class POAttainmentRun(Document):
	def validate(self):
		attainment.set_po_scope(self)
		scope = {
			"program": self.program,
			"batch": self.batch,
			"academic_year": self.academic_year or ["is", "not set"],
		}
		attainment.check_one_live(self, scope, ("Program", self.program))

	def before_submit(self):
		if self.status != "Computed":
			frappe.throw(_("Compute the run before submitting it."))
