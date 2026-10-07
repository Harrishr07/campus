"""M05-02 Attendance Eligibility Run: a frozen term snapshot of every student's attendance eligibility.

The work lives in campus.student_services.eligibility_run; this controller validates the run's scope.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.student_services import eligibility_run


class AttendanceEligibilityRun(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if before and (before.locked or self.locked != before.locked):
			frappe.throw(_("{0} is locked; use Lock to freeze a run and nothing else can change it.").format(self.name))
		if self.program and frappe.db.get_value("Program", self.program, "oc_company") != self.company:
			frappe.throw(_("Program {0} does not belong to {1}.").format(frappe.bold(self.program), frappe.bold(self.company)))
		self.run_key = eligibility_run.run_key(self)
		if frappe.db.exists(self.doctype, {"run_key": self.run_key, "name": ["!=", self.name]}):
			frappe.throw(_("A run for this company, term, programme and semester already exists; run that one again."))

	def on_trash(self):
		if self.locked:
			frappe.throw(_("{0} is locked and cannot be deleted.").format(self.name))

	@frappe.whitelist()
	def start_run(self):
		return eligibility_run.start(self)

	@frappe.whitelist()
	def lock_run(self):
		eligibility_run.lock(self)
