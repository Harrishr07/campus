"""M06-06 Result Ratification: the COE's "ratify revised results" of a published Exam Session.

A re-run after publication (revaluation, an approved withdrawal) makes pending Student Result versions; the
published version stays the one students, guardians and staff see. A Result Ratification lists the session's
pending versions (refreshed on every draft save) and goes through the approval engine (seeded policy: the
Principal of the company; the requester and owner never approve); only the final approval submits it. On submit
each listed version whose changes are still the ones listed becomes the latest (the one it replaces stays readable
to the COE) and its student and guardians are notified. Not cancellable: a ratified version is published.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_messaging.api import send
from campus.campus_platform.api import ApprovableDocument, is_approved

RESULT = "Student Result"
REVISED_EVENT = "exam.result_revised"


class ResultRatification(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		if frappe.db.get_value("Exam Session", self.exam_session, "status") != "Published":
			frappe.throw(_("Only the results of a published Exam Session are ratified."))
		if self.docstatus == 0:  # an approval-driven submit ratifies what the approver saw
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
			if publish_version(item.student_result, item.change_log, self.name):
				notify(item.student_result)


def pending_items(exam_session):
	return [
		{"student_result": r.name, "student": r.student, "version": r.version, "change_log": r.change_log}
		for r in frappe.get_all(
			RESULT, {"exam_session": exam_session, "pending_ratification": 1}, ["name", "student", "version", "change_log"], order_by="student"
		)
	]


def publish_version(name, change_log, ratification):
	"""Make the pending version `name` the latest; False when it is gone or its changes moved since listing."""
	row = frappe.db.get_value(RESULT, name, ["student", "exam_session", "pending_ratification", "change_log"], as_dict=True, for_update=True)
	if not row or not row.pending_ratification or (row.change_log or "") != (change_log or ""):
		return False
	for old in frappe.get_all(RESULT, {"student": row.student, "exam_session": row.exam_session, "is_latest": 1}, pluck="name"):
		frappe.db.set_value(RESULT, old, "is_latest", 0, update_modified=False)
	frappe.db.set_value(RESULT, name, {"is_latest": 1, "pending_ratification": 0, "ratification": ratification})
	return True


def notify(name):
	doc = frappe.get_doc(RESULT, name)
	guardians = frappe.get_all("Student Guardian", {"parent": doc.student, "parenttype": "Student"}, pluck="guardian", order_by="idx")
	send(REVISED_EVENT, doc, [f"Student:{doc.student}", *(f"Guardian:{g}" for g in guardians)])
