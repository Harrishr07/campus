"""M06-02 Malpractice Report: an exam-hall incident (category, private evidence) and the committee's decision.

Approved through the generic approval engine (seeded policy: the COE of the company); only the final approval
submits it. A submitted report whose decision is Debarment debars the student's Exam Registration of the
session (T14's flag: every course becomes "Not eligible (Debarred)"); cancelling it lifts that debarment.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_platform.api import ApprovableDocument, is_approved
from campus.examinations.doctype.exam_registration.exam_registration import registration_name

DEBARMENT = "Debarment"
PRIVATE = "/private/files/"


class MalpracticeReport(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.company = frappe.db.get_value("Exam Session", self.exam_session, "company")
		self.exam_registration = registration_name(self.exam_session, self.student)
		if not frappe.db.exists("Exam Registration", self.exam_registration):
			frappe.throw(_("{0} has no Exam Registration in {1}.").format(frappe.bold(self.student), self.exam_session))
		for row in self.evidence:
			if not (row.file or "").startswith(PRIVATE):
				frappe.throw(_("Evidence row {0}: attach the file as private.").format(row.idx))

	def before_submit(self):
		super().before_submit()
		if not is_approved(self):  # without a policy the engine would submit directly: a decision always needs one
			frappe.throw(
				_("A Malpractice Report is submitted only by its approval. Set up an Approval Policy for Malpractice Report."),
				title=_("Approval Required"),
			)
		if not self.committee_decision:
			frappe.throw(_("Record the committee decision before approval."))

	def on_submit(self):
		if self.committee_decision == DEBARMENT:
			self.set_debarment(True)

	def on_cancel(self):
		if self.committee_decision == DEBARMENT:
			self.set_debarment(False)

	def set_debarment(self, debar):
		registration = frappe.get_doc("Exam Registration", self.exam_registration, for_update=True)
		if debar and not registration.debarred:
			registration.debarred, registration.debarment_reason = 1, self.debarment_reason()
		elif not debar and registration.debarment_reason == self.debarment_reason():
			registration.debarred, registration.debarment_reason = 0, None
		else:
			return  # debarred already for another reason, or lifted by someone else: leave it
		registration.save(ignore_permissions=True)  # the approver need not hold write on registrations

	def debarment_reason(self):
		return _("Malpractice {0}: {1}").format(self.name, _(self.category))
