"""M06-02 Malpractice Report: an exam-hall incident (category, private evidence) and the committee's decision.

Confidential: the exam office (COE, System Manager), the Principal and Dean Academics read every report; an
invigilator (Academics User) files reports and reads only their own. Evidence must be private Files, and they
are attached to the report, so opening one needs read on the report.

Approved through the generic approval engine (seeded policy: the COE position of the company, which suits reports
filed by invigilators; a report the COE files should go to a Principal-level policy). Only the final approval
submits it. A submitted report whose decision is Debarment debars the student's Exam Registration of the session
(T14's flag: every course becomes "Not eligible (Debarred)"); only a System Manager may cancel it, which lifts
that debarment.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_platform.api import ApprovableDocument, is_approved
from campus.examinations.doctype.exam_registration.exam_registration import registration_name

DEBARMENT = "Debarment"
EVIDENCE_FIELD = "evidence"


class MalpracticeReport(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.company = frappe.db.get_value("Exam Session", self.exam_session, "company")
		self.exam_registration = registration_name(self.exam_session, self.student)
		if not frappe.db.exists("Exam Registration", self.exam_registration):
			frappe.throw(_("{0} has no Exam Registration in {1}.").format(frappe.bold(self.student), self.exam_session))
		if not frappe.db.exists(
			"Exam Registration Course", {"parent": self.exam_registration, "parenttype": "Exam Registration", "course": self.course}
		):
			frappe.throw(_("{0} is not registered for {1} in this session.").format(frappe.bold(self.student), frappe.bold(self.course)))
		for row in self.evidence:
			self.validate_evidence(row)

	def validate_evidence(self, row):
		files = frappe.get_all(
			"File", {"file_url": row.file, "is_private": 1}, ["attached_to_doctype", "attached_to_name"]
		)
		if not files:
			frappe.throw(_("Evidence row {0}: upload the file as private.").format(row.idx))
		if not any(owned_by_this(f, self) for f in files):
			frappe.throw(_("Evidence row {0}: the file is attached to another document.").format(row.idx))

	def on_update(self):
		"""Attach the uploaded evidence to this report, so the File's access follows the report's."""
		for row in self.evidence:
			for file in frappe.get_all("File", {"file_url": row.file, "is_private": 1, "attached_to_doctype": ["is", "not set"]}, pluck="name"):
				frappe.db.set_value(
					"File", file, {"attached_to_doctype": self.doctype, "attached_to_name": self.name, "attached_to_field": EVIDENCE_FIELD}
				)

	def before_submit(self):
		super().before_submit()
		if not is_approved(self):  # without a policy the engine would submit directly: a decision always needs one
			frappe.throw(
				_("A Malpractice Report is submitted only by its approval. Set up an Approval Policy for Malpractice Report."),
				title=_("Approval Required"),
			)
		if not self.committee_decision:
			frappe.throw(_("Record the committee decision before approval."))

	def before_cancel(self):
		frappe.only_for("System Manager")  # undoing an approved committee decision is not the exam office's call

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
		elif not debar and (registration.debarment_reason or "").startswith(f"Malpractice {self.name}:"):
			registration.debarred, registration.debarment_reason = 0, None
		else:
			return  # debarred already for another reason, or lifted by someone else: leave it
		registration.save(ignore_permissions=True)  # the approver need not hold write on registrations

	def debarment_reason(self):
		"""Stored untranslated: it is data matched on cancel, shown as is."""
		return f"Malpractice {self.name}: {self.category}"


def owned_by_this(file, report):
	unattached = not file.attached_to_doctype
	return unattached or (file.attached_to_doctype == report.doctype and file.attached_to_name == report.name)
