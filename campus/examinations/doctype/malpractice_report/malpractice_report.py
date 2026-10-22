"""M06-02 Malpractice Report: an exam-hall incident (category, private evidence) and the committee's decision.

Confidential: the exam office (COE, System Manager), the Principal and Dean Academics read every report; an
invigilator (Academics User) files reports and reads only their own. Evidence must be private Files the filer
uploaded (or already attached to this report or the report it amends); they are attached to the report, so
opening one needs read on the report. The committee decision is the COE's: it sits at permlevel 1 (COE and
System Manager write it, the seeded approval level lets the approver edit it) and submit needs a decision
recorded by one of them (decision_set_by).

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
from campus.examinations.access import MARKS_ROLES, has_any_role
from campus.examinations.doctype.exam_registration.exam_registration import registration_name

DEBARMENT = "Debarment"
EVIDENCE_FIELD = "evidence"


class MalpracticeReport(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.check_amend_right()
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
		self.track_decision()

	def check_amend_right(self):
		"""An amendment inherits the original's evidence (and Frappe copies its attachments after insert): only someone
		who may amend the original may start one."""
		if self.is_new() and self.amended_from and not frappe.has_permission(self.doctype, "amend", doc=self.amended_from):
			frappe.throw(_("You may not amend {0}.").format(self.amended_from), frappe.PermissionError)

	def validate_evidence(self, row):
		files = frappe.get_all("File", {"file_url": row.file}, ["owner", "is_private", "attached_to_doctype", "attached_to_name"])
		if not files or not all(f.is_private for f in files):
			frappe.throw(_("Evidence row {0}: upload the file as private.").format(row.idx))
		if not all(self.may_claim(f) for f in files):
			frappe.throw(_("Evidence row {0}: the file belongs to another user or another document.").format(row.idx))

	def may_claim(self, file):
		"""An unattached File its uploader (the filer) claims, or one already attached to this report or its original."""
		if not file.attached_to_doctype:
			return file.owner in (frappe.session.user, self.owner)
		return file.attached_to_doctype == self.doctype and file.attached_to_name in (self.name, self.amended_from)

	def track_decision(self):
		before = self.get_doc_before_save()
		old = (before.committee_decision, before.decision_remarks) if before else (None, None)
		if (self.committee_decision or None, self.decision_remarks or None) == tuple(v or None for v in old):
			return
		if not has_any_role(frappe.session.user, MARKS_ROLES):
			frappe.throw(_("Only the COE records the committee decision."))
		self.decision_set_by = frappe.session.user if self.committee_decision else None

	def on_update(self):
		"""Attach the uploaded evidence to this report, so the File's access follows the report's."""
		for row in self.evidence:
			unattached = {"file_url": row.file, "is_private": 1, "attached_to_doctype": ["is", "not set"]}
			for file in frappe.get_all("File", unattached, pluck="name"):
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
		if not self.committee_decision or not (self.decision_set_by and has_any_role(self.decision_set_by, MARKS_ROLES)):
			frappe.throw(_("The COE must record the committee decision before approval."))

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

