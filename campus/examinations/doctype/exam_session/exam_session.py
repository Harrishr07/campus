"""M12-02 Exam Session: one examination of a company in an academic term (Draft, Marks Entry, Published)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime


class ExamSession(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if before and before.status == "Published" and self.status != "Published":
			frappe.throw(_("A published Exam Session cannot be reopened."))
		if before and before.status == "Published" and get_datetime(before.publish_at) != get_datetime(self.publish_at):
			frappe.throw(_("The publication time of a published Exam Session cannot change."))
		if frappe.db.exists(
			"Exam Session", {"company": self.company, "academic_term": self.academic_term, "name": ["!=", self.name]}
		):
			frappe.throw(_("{0} already has an Exam Session for {1}.").format(self.company, self.academic_term))
