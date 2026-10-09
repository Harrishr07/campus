"""M06-06 Result Ratification: the COE's "ratify revised results" of a published Exam Session.

A re-run after publication (revaluation, an approved withdrawal) makes pending Student Result versions; the
published version stays the one students, guardians and staff see. A Result Ratification lists the session's
pending versions (refreshed on every draft save) and goes through the approval engine (seeded policy: the
Principal of the company; the requester and owner never approve); only the final approval submits it. On submit
each listed version whose grading (marks, grace, grades, results, GPAs: its fingerprint) is still the one listed
becomes the latest (the one it replaces stays readable
to the COE) and its student and guardians are notified; a valid Grade Sheet of the replaced version is revoked and
re-issued for the new one. Not cancellable: a ratified version is published.
"""

import hashlib
import json

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_messaging.api import send
from campus.campus_platform.api import ApprovableDocument, is_approved

RESULT = "Student Result"
REVISED_EVENT = "exam.result_revised"
GRADE_SHEET = "Grade Sheet"
REISSUE_JOB = "campus.examinations.doctype.result_ratification.result_ratification.issue_grade_sheet"


class ResultRatification(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		if frappe.db.get_value("Exam Session", self.exam_session, "status") != "Published":
			frappe.throw(_("Only the results of a published Exam Session are ratified."))
		if self.docstatus == 0 and not approval_requested(self):  # the approver ratifies the list they were asked about
			self.set("items", pending_items(self.exam_session))
		if not self.items:
			frappe.throw(_("{0} has no pending result version to ratify.").format(frappe.bold(self.exam_session)))

	def before_submit(self):
		super().before_submit()
		if not is_approved(self):
			frappe.throw(
				_("A Result Ratification is submitted only by its approval. Set up an Approval Policy for Result Ratification."),
				title=_("Approval Required"),
			)

	def on_submit(self):
		for item in self.items:
			replaced = publish_version(item.student_result, item.fingerprint, self.name)
			if replaced is not None:
				reissue_grade_sheets(replaced, item.student_result)
				notify(item.student_result)


def approval_requested(doc):
	return not doc.is_new() and bool(frappe.db.exists("Approval Request", {"reference_doctype": doc.doctype, "reference_name": doc.name}))


def pending_items(exam_session):
	return [
		{"student_result": r.name, "student": r.student, "version": r.version, "change_log": r.change_log, "fingerprint": fingerprint(r.name)}
		for r in frappe.get_all(
			RESULT, {"exam_session": exam_session, "pending_ratification": 1}, ["name", "student", "version", "change_log"], order_by="student"
		)
	]


GRADING_FIELDS = ("course", "kind", "cia", "ese", "moderation", "grace", "total", "grade", "grade_point", "result")


def fingerprint(name):
	"""A digest of what grades the version: every course row's marks, grace, grade and result, its GPAs, result,
	arrears and classification."""
	doc = frappe.get_doc(RESULT, name)
	rows = [[str(row.get(f)) for f in GRADING_FIELDS] for row in doc.courses]
	summary = [str(doc.sgpa), str(doc.cgpa), doc.result, doc.arrear_count, doc.classification or ""]
	return hashlib.sha256(json.dumps([rows, summary]).encode()).hexdigest()


def publish_version(name, listed_fingerprint, ratification):
	"""Make the pending version `name` the latest; returns the versions it replaces, or None when it is gone or its
	grading changed since listing."""
	row = frappe.db.get_value(RESULT, name, ["student", "exam_session", "pending_ratification"], as_dict=True, for_update=True)
	if not row or not row.pending_ratification or fingerprint(name) != listed_fingerprint:
		return None
	replaced = frappe.get_all(RESULT, {"student": row.student, "exam_session": row.exam_session, "is_latest": 1}, pluck="name")
	for old in replaced:
		frappe.db.set_value(RESULT, old, "is_latest", 0, update_modified=False)
	frappe.db.set_value(RESULT, name, {"is_latest": 1, "pending_ratification": 0, "ratification": ratification})
	return replaced


def reissue_grade_sheets(replaced, name):
	"""A replaced version's valid Grade Sheet is revoked now and one is issued for the ratified version after commit
	(P2-T20): a grade sheet always shows the published grades and CGPA. The approver usually has no print right on
	Student Result, so the new sheet is rendered in a job (Administrator in the worker, as the exam fee invoice)."""
	from campus.campus_platform.verification import revoke_for

	issued = False
	for old in replaced:
		filters = {"reference_doctype": RESULT, "reference_name": old, "print_format": GRADE_SHEET, "status": "Valid"}
		if frappe.db.exists("Verifiable Document", filters):
			revoke_for(frappe.get_doc(RESULT, old), _("Superseded by the ratified version {0}").format(name))
			issued = True
	if issued:
		frappe.enqueue(REISSUE_JOB, queue="short", enqueue_after_commit=True, now=frappe.in_test, student_result=name)


def issue_grade_sheet(student_result):
	"""Worker entry point: issue the Grade Sheet of a ratified version that has no valid one (idempotent)."""
	from campus.campus_platform.verification import issue

	caller = frappe.session.user
	frappe.set_user("Administrator")
	try:
		filters = {"reference_doctype": RESULT, "reference_name": student_result, "print_format": GRADE_SHEET, "status": "Valid"}
		if frappe.db.get_value(RESULT, student_result, "is_latest") and not frappe.db.exists("Verifiable Document", filters):
			issue(frappe.get_doc(RESULT, student_result), GRADE_SHEET)
	finally:
		frappe.set_user(caller)


def notify(name):
	doc = frappe.get_doc(RESULT, name)
	guardians = frappe.get_all("Student Guardian", {"parent": doc.student, "parenttype": "Student"}, pluck="guardian", order_by="idx")
	send(REVISED_EVENT, doc, [f"Student:{doc.student}", *(f"Guardian:{g}" for g in guardians)])
