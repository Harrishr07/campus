"""M06-06 Result Ratification: the COE's "ratify revised results" of a published Exam Session.

A re-run after publication (revaluation, an approved withdrawal) makes pending Student Result versions; the
published version stays the one students, guardians and staff see. A Result Ratification lists the session's
pending versions (refreshed on every draft save) and goes through the approval engine (seeded policy: the
Principal of the company; the requester and owner never approve); only the final approval submits it. On submit
each listed version whose grading (marks, grace, grades, results, GPAs: its fingerprint) is still the one listed
becomes the latest (the one it replaces stays readable
to the COE) and its student and guardians are notified; a valid Grade Sheet of the replaced version is revoked and
re-issued for the new one, and the student's results of later sessions are recomputed on it (pending versions where
those are published). Not cancellable: a ratified version is published.
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
				reissue_grade_sheets(replaced, item.student_result, self.name)
				notify(item.student_result)
				refresh_later_results(item.student, self.exam_session, self.name)


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


def reissue_grade_sheets(replaced, name, ratification):
	"""A replaced version's valid Grade Sheet is revoked now and one is issued for the ratified version after commit
	(P2-T20): a grade sheet always shows the published grades and CGPA. The approver usually has no print right on
	Student Result, so the new sheet is rendered in a job (Administrator in the worker, as the exam fee invoice)."""
	from campus.campus_platform.verification import revoke_for

	issued = False
	for old in replaced:
		filters = {"reference_doctype": RESULT, "reference_name": old, "print_format": GRADE_SHEET, "status": "Valid"}
		if frappe.db.exists("Verifiable Document", filters):
			revoke_for(frappe.get_doc(RESULT, old), _("Superseded by the version {0} ratified by {1}").format(name, ratification))
			issued = True
	if issued:
		frappe.enqueue(
			REISSUE_JOB, queue="short", enqueue_after_commit=True, now=frappe.in_test, student_result=name, ratification=ratification
		)


def issue_grade_sheet(student_result, ratification):
	"""Worker entry point: issue the Grade Sheet of a ratified version that has no valid one (idempotent). A failure
	is logged with the ratification; the COE then issues it with Issue Grade Sheet."""
	from campus.campus_platform import verification

	caller = frappe.session.user
	frappe.set_user("Administrator")
	try:
		filters = {"reference_doctype": RESULT, "reference_name": student_result, "print_format": GRADE_SHEET, "status": "Valid"}
		if frappe.db.get_value(RESULT, student_result, "is_latest") and not frappe.db.exists("Verifiable Document", filters):
			frappe.db.savepoint("grade_sheet_reissue")
			try:
				verification.issue(frappe.get_doc(RESULT, student_result), GRADE_SHEET)
			except Exception as e:
				frappe.db.rollback(save_point="grade_sheet_reissue")
				frappe.log_error(
					title=_("Grade Sheet re-issue failed ({0})").format(ratification),
					message=_("Ratification {0}: the Grade Sheet of {1} was not issued: {2}. Issue it with Issue Grade Sheet.").format(
						ratification, student_result, e
					),
				)
	finally:
		frappe.set_user(caller)


def refresh_later_results(student, exam_session, ratification):
	"""Recompute the student's results of the sessions that read the ratified version (P2-T20): those of later terms
	and the other sessions of the same term (a supplementary; results.earlier_rows reads terms starting no later), as
	their CGPA and arrears read it. A published session gets a pending version (its own ratification publishes it and
	re-issues its sheet); an unpublished one is replaced in place. A session that cannot be recomputed is logged with
	an explicit message and never blocks this one or the others, except a deadlock or lock wait timeout, which is
	raised (the transaction is gone)."""
	from campus.examinations.results import compute_student_result

	start = frappe.db.get_value("Academic Term", frappe.db.get_value("Exam Session", exam_session, "academic_term"), "term_start_date")
	result, term = frappe.qb.DocType(RESULT), frappe.qb.DocType("Academic Term")
	later = (
		frappe.qb.from_(result)
		.join(term).on(term.name == result.academic_term)
		.select(result.exam_session).distinct()
		.where((result.student == student) & (result.is_latest == 1) & (result.exam_session != exam_session) & (term.term_start_date >= start))
		.orderby(term.term_start_date)
		.run(pluck=True)
	)  # fmt: skip
	for session in later:
		frappe.db.savepoint("later_result")
		try:
			compute_student_result(student, session)
		except Exception as e:
			if frappe.db.is_deadlocked(e) or frappe.db.is_timedout(e):
				raise  # the database rolled the transaction (and its savepoint) back: the ratification must fail too
			frappe.db.rollback(save_point="later_result")
			frappe.clear_messages()
			frappe.log_error(
				title=_("Later result not refreshed ({0})").format(ratification),
				message=_("Ratification {0}: the result of {1} in {2} was not recomputed: {3}").format(ratification, student, session, e),
			)


def notify(name):
	doc = frappe.get_doc(RESULT, name)
	guardians = frappe.get_all("Student Guardian", {"parent": doc.student, "parenttype": "Student"}, pluck="guardian", order_by="idx")
	send(REVISED_EVENT, doc, [f"Student:{doc.student}", *(f"Guardian:{g}" for g in guardians)])
