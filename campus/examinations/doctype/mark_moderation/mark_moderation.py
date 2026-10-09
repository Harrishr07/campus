"""M06-05 Mark Moderation: an ESE adjustment, in marks, for every student who sat one course of an Exam Session,
with its justification.

Approved through the generic approval engine (seeded policy: the Principal of the company; the requester and
owner never approve); only the final approval submits it. The Result Run applies the submitted moderation of a
course (campus.examinations.results) and shows it on each course row. One live moderation per session and
course; none is proposed, submitted or cancelled once the session is Published.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from campus.campus_platform.api import ApprovableDocument, is_approved

PUBLISHED = "Published"


class MarkModeration(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.check_session()
		if not flt(self.adjustment):
			frappe.throw(_("The ESE adjustment cannot be zero."))
		if not (self.justification or "").strip():
			frappe.throw(_("Give the justification for the moderation."))
		if not frappe.db.exists("Mark Sheet Entry", {"exam_session": self.exam_session, "course": self.course}):
			frappe.throw(_("{0} has no Mark Sheet Entry in {1}.").format(frappe.bold(self.course), frappe.bold(self.exam_session)))
		self.check_duplicate()

	def before_submit(self):
		super().before_submit()
		if not is_approved(self):  # without a policy the engine would submit directly: a moderation always needs one
			frappe.throw(
				_("A Mark Moderation is submitted only by its approval. Set up an Approval Policy for Mark Moderation."),
				title=_("Approval Required"),
			)

	def before_cancel(self):
		self.check_session()

	def check_session(self):
		session = frappe.db.get_value("Exam Session", self.exam_session, ["company", "status"], as_dict=True)
		self.company = session.company
		if session.status == PUBLISHED:
			frappe.throw(_("The results of {0} are published; its marks can no longer be moderated.").format(frappe.bold(self.exam_session)))

	def check_duplicate(self):
		other = frappe.db.get_value(
			"Mark Moderation",
			{"exam_session": self.exam_session, "course": self.course, "docstatus": ["<", 2], "name": ["!=", self.name]},
		)
		if other:
			frappe.throw(_("{0} already moderates {1} in this session.").format(frappe.bold(other), frappe.bold(self.course)))


def approved_adjustments(exam_session):
	"""{course: ESE marks} of the session's submitted moderations."""
	return dict(
		frappe.get_all("Mark Moderation", {"exam_session": exam_session, "docstatus": 1}, ["course", "adjustment"], as_list=True)
	)
