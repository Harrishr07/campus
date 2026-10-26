"""M06-03 Question Paper: the pattern (blueprint), sets A/B of bank questions, moderation and the encrypted PDFs.

Access, the release window and the access log live in campus.examinations.question_papers. Moderation goes through
the Phase-1 approval engine (policy "Question Paper Moderation": Exam Confidential of the college; the engine never
lets the setter or the requester approve). A request is refused unless the paper could be sealed: blueprint check
(CO coverage, Bloom distribution: question_paper_rules), release time, Set A and every attached set sealed for this
paper. The final approval submits the paper: that seals it, snapshots its download window from the settings, and
allows one approved paper per exam session and course, and snapshots each sealed File (name, SHA-256). Besides the
requester and the owner, the nominated setters of the course and every user who changed the paper's content never
approve it. Withdrawn is one-way; a withdrawn sealed paper stays closed and is never amended, copied or deleted.
Release At is always the slot start of the course in the session's schedule.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from campus.campus_platform import approval_rules
from campus.campus_platform.approval_engine import find_policy, latest_request
from campus.campus_platform.approvals import ApprovableDocument
from campus.examinations.question_paper_files import PAPER_FILE_FIELDS, bound_file, seal_attachments, snapshot
from campus.examinations.question_paper_rules import blueprint_issues
from campus.examinations.question_papers import APPROVED, WITHDRAWN, log_once, slot_start, window_for

UNDER_MODERATION = "Under Moderation"


class QuestionPaper(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.refuse_change_once_withdrawn()
		if self.amended_from:
			frappe.throw(_("A question paper cannot be amended or copied; create and moderate a new one."))
		self.company = frappe.db.get_value("Exam Session", self.exam_session, "company")
		self.release_at = slot_start(self.exam_session, self.course)
		self.validate_questions()
		seal_attachments(self)
		self.record_editor()
		self.blueprint_issues = "\n".join(self.check_blueprint()) or None
		if self.docstatus == 0 and self.moderation_status != WITHDRAWN:
			pending = (latest_request(self) or {}).get("status") == approval_rules.PENDING
			self.moderation_status = UNDER_MODERATION if pending else "Draft"

	def onload(self):
		super().onload()
		log_once(self, "View", True, "", frappe.session.user)  # the desk form, Administrator included
		if self.docstatus == 1:
			self.set("questions", [])  # a sealed paper's questions never reach a browser

	def before_approval_request(self):
		if self.moderation_status == WITHDRAWN:
			frappe.throw(_("A withdrawn paper cannot be sent for approval."))
		if not find_policy(self):
			frappe.throw(
				_("Set up an Approval Policy for Question Paper first: a paper is sealed only by moderation.")
			)
		self.validate_sealable()
		self.db_set("moderation_status", UNDER_MODERATION)

	def before_submit(self):
		super().before_submit()
		latest = latest_request(self)
		if not latest or latest.status != approval_rules.APPROVED:
			frappe.throw(_("A question paper is sealed only by its moderation approval."))
		self.validate_sealable()
		self.refuse_second_approved_paper()
		self.download_opens_at, self.download_closes_at = window_for(self.release_at)
		snapshot(self)
		self.moderation_status = APPROVED

	def on_cancel(self):
		self.db_set("moderation_status", WITHDRAWN)

	def on_trash(self):
		if self.docstatus != 0:
			frappe.throw(_("An approved or withdrawn question paper is never deleted."))
		super().on_trash()

	def approval_excluded_users(self):
		"""Users who never approve this paper (with the engine's requester and owner): its editors and the nominated
		setters of the course in the session."""
		nominations = frappe.get_all(
			"QP Setter Nomination", {"exam_session": self.exam_session, "course": self.course}, pluck="name"
		)
		employees = frappe.get_all(
			"QP Nomination Setter", {"parent": ["in", nominations or [""]]}, pluck="employee"
		)
		setters = frappe.get_all(
			"Employee", {"name": ["in", employees or [""]], "user_id": ["is", "set"]}, pluck="user_id"
		)
		items = [q.question_item for q in self.questions] or [""]
		item_editors = frappe.get_all("Question Bank Item", {"name": ["in", items]}, pluck="editors")
		return {*setters, *(self.editors or "").split(), *" ".join(e or "" for e in item_editors).split()}

	def record_editor(self):
		"""Server-owned: the saved editors, plus the session user when the content changed; a client value is ignored."""
		before = self.get_doc_before_save()
		editors = (before.editors or "").split() if before else []
		if (
			not before or content_signature(before) != content_signature(self)
		) and frappe.session.user not in editors:
			editors.append(frappe.session.user)
		self.editors = "\n".join(editors) or None

	def refuse_change_once_withdrawn(self):
		before = self.get_doc_before_save()
		if before and before.moderation_status == WITHDRAWN:
			frappe.throw(_("Question Paper {0} is withdrawn; it cannot be changed.").format(self.name))

	def validate_questions(self):
		seen = set()
		for row in self.questions:
			course, company, disabled, retired = frappe.db.get_value(
				"Question Bank Item",
				row.question_item,
				["course", "company", "disabled", "retired_by_withdrawal"],
			)
			if retired:
				frappe.throw(
					_("Row {0}: {1} was on withdrawn paper {2} and is retired.").format(
						row.idx, row.question_item, retired
					)
				)
			if course != self.course or company != self.company:
				frappe.throw(
					_("Row {0}: {1} is not a question of {2} in {3}.").format(
						row.idx, row.question_item, self.course, self.company
					)
				)
			if disabled:
				frappe.throw(_("Row {0}: {1} is disabled.").format(row.idx, row.question_item))
			if (row.paper_set, row.question_item) in seen:
				frappe.throw(
					_("Row {0}: {1} is already in Set {2}.").format(row.idx, row.question_item, row.paper_set)
				)
			seen.add((row.paper_set, row.question_item))

	def check_blueprint(self):
		questions = [{"paper_set": q.paper_set, "course_outcome": q.course_outcome, "bloom_level": q.bloom_level,
			"marks": q.marks} for q in self.questions]  # fmt: skip
		with_files = [s for s, field in PAPER_FILE_FIELDS.items() if self.get(field)]
		return blueprint_issues(
			questions, [r.as_dict() for r in self.blueprint], self.total_marks, with_files
		)

	def validate_sealable(self):
		if not self.release_at:
			frappe.throw(_("Set Release At before approving the paper."))
		if now_datetime() >= window_for(self.release_at)[0]:
			frappe.throw(
				_("The download window of this paper has already opened; it is too late to seal it.")
			)
		if not self.set_a_file:
			frappe.throw(_("Attach the Set A paper before approving."))
		for field in PAPER_FILE_FIELDS.values():
			if self.get(field) and not bound_file(self, field):
				frappe.throw(_("{0} is not a sealed file of this paper.").format(self.meta.get_label(field)))
		issues = "\n".join(self.check_blueprint())
		if issues:
			frappe.throw(_("The paper does not match its blueprint:") + "<br>" + issues.replace("\n", "<br>"))

	def refuse_second_approved_paper(self):
		frappe.db.get_value(
			"Exam Session", self.exam_session, "name", for_update=True
		)  # one approval at a time
		other = frappe.db.get_value(
			"Question Paper",
			{"exam_session": self.exam_session, "course": self.course, "docstatus": 1, "name": ["!=", self.name]},
			"name", for_update=True,
		)  # fmt: skip
		if other:
			frappe.throw(
				_("{0} is already the approved paper of {1} in this session.").format(other, self.course)
			)


def content_signature(doc):
	"""What a setter writes: the questions, the pattern, the marks and the files."""
	return (
		[(q.paper_set, q.question_item) for q in doc.questions],
		[(r.criterion, r.value, r.min_percent, r.max_percent) for r in doc.blueprint],
		doc.total_marks, doc.set_a_file, doc.set_b_file,
	)  # fmt: skip
