"""M02-02, M02-04 Academic Proposal: a proposed curriculum or regulation change that must pass the bodies of its
Proposal Type in order. Each stage is passed by a resolution of a quorate meeting of that body that references the
proposal (see proposals.find_resolution); the last one makes the Curriculum (for the listed batches) and the
Regulation Effective. Changes are versioned (track_changes) and comments stay on the record for IQAC."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.academic_governance import proposal_approval, proposals

SERVER_FIELDS = ("status", "current_stage", "current_body_type", "approved_on", "approving_resolution")
SUBJECT_FIELDS = ("proposal_type", "company", "department", "regulation", "curriculum")


class AcademicProposal(Document):
	def validate(self):
		self.protect_server_fields()
		if self.status in ("Approved", "Rejected"):
			return
		self.validate_subject()
		self.validate_unchanged_subject()

	def on_trash(self):
		if self.status != "Draft":
			frappe.throw(_("Only a Draft proposal can be deleted."))

	@property
	def proposal_type_doc(self):
		return frappe.get_cached_doc("Proposal Type", self.proposal_type)

	def protect_server_fields(self):
		"""Status, stage and resolutions are set only by submit_to_route / advance_stage."""
		if self.flags.advancing:
			return
		before = self.get_doc_before_save()
		if not before:
			self.update({field: None for field in SERVER_FIELDS})
			self.status, self.current_stage = "Draft", 0
			self.set("stage_resolutions", [])
			return
		if before.status in ("Approved", "Rejected"):
			frappe.throw(_("{0} is {1} and cannot be changed.").format(frappe.bold(self.name), _(before.status)))
		self.update({field: before.get(field) for field in SERVER_FIELDS})
		self.set("stage_resolutions", [row.as_dict() for row in before.stage_resolutions])

	def validate_unchanged_subject(self):
		before = self.get_doc_before_save()
		if not before or before.status == "Draft":
			return
		changed = [f for f in SUBJECT_FIELDS if self.get(f) != before.get(f)]
		changed += [t for t in ("batches", "courses") if listed(self, t) != listed(before, t)]
		if changed:
			frappe.throw(_("The route has started; {0} can no longer change.").format(", ".join(_(self.meta.get_label(f)) for f in changed)))

	def validate_subject(self):
		kind = self.proposal_type_doc
		curriculum = self.curriculum and frappe.db.get_value("Curriculum", self.curriculum, ["regulation", "status"], as_dict=True)
		if kind.requires_curriculum and not self.curriculum:
			frappe.throw(_("A {0} proposal needs a Curriculum Draft.").format(_(self.proposal_type)))
		if curriculum:
			self.regulation = self.regulation or curriculum.regulation
			if curriculum.regulation != self.regulation:
				frappe.throw(_("Curriculum {0} belongs to regulation {1}, not {2}.").format(self.curriculum, curriculum.regulation, self.regulation))
		if kind.changes_regulation and not self.regulation:
			frappe.throw(_("A {0} proposal needs a Regulation.").format(_(self.proposal_type)))
		if curriculum and self.status == "Draft" and curriculum.status not in proposal_approval.OPEN_STATUSES:
			frappe.throw(_("Curriculum {0} is {1}; propose a new version instead.").format(frappe.bold(self.curriculum), _(curriculum.status)))
		self.validate_company()
		self.validate_batches()

	def validate_company(self):
		for doctype, name in (("Department", self.department), ("Regulation", self.regulation)):
			company = name and frappe.db.get_value(doctype, name, "company")
			if company and company != self.company:
				frappe.throw(_("{0} {1} belongs to {2}, not {3}.").format(_(doctype), frappe.bold(name), company, self.company))

	def validate_batches(self):
		years = listed(self, "batches")
		if len(years) != len(set(years)):
			frappe.throw(_("A batch is listed more than once."))

	@frappe.whitelist()
	def submit_to_route(self):
		"""Start the route at its first body. Checks that the subject can still be made Effective."""
		self.check_permission("write")
		if self.status != "Draft":
			frappe.throw(_("Only a Draft proposal can be submitted."))
		self.validate_ready_for_approval()
		self.status, self.current_stage = "In Route", 1
		self.current_body_type = self.proposal_type_doc.route[0].body_type
		self.save_as_server()
		return self.status

	def validate_ready_for_approval(self):
		if self.curriculum:
			status = frappe.db.get_value("Curriculum", self.curriculum, "status")
			if status not in proposal_approval.OPEN_STATUSES:
				frappe.throw(_("Curriculum {0} is {1}; propose a new version instead.").format(frappe.bold(self.curriculum), _(status)))
			if not self.batches:
				frappe.throw(_("List the batches this curriculum is effective for."))
		if self.proposal_type_doc.changes_regulation:
			status = frappe.db.get_value("Regulation", self.regulation, "status")
			if status not in proposal_approval.OPEN_STATUSES:
				frappe.throw(_("Regulation {0} is {1}; amend it as a new version and propose that.").format(frappe.bold(self.regulation), _(status)))

	@frappe.whitelist()
	def advance_stage(self):
		"""Move past the current stage on the strength of its resolution; the last stage approves the proposal."""
		self.check_permission("write")
		if self.status != "In Route":
			frappe.throw(_("{0} is {1}, not in route.").format(frappe.bold(self.name), _(self.status)))
		route = [row.body_type for row in self.proposal_type_doc.route]
		previous = self.stage_resolutions[-1].resolution_date if self.stage_resolutions else None
		found = proposals.find_resolution(self, self.current_body_type, previous)
		if not found:
			frappe.throw(
				_("No resolution of a quorate meeting of {0} decides this proposal yet. Record it in the meeting's resolutions first.").format(
					frappe.bold(self.current_body_type)
				),
				title=_("Resolution Needed"),
			)
		frappe.db.savepoint("academic_proposal_advance")
		try:
			self.record_stage(found, route)
		except Exception:
			frappe.db.rollback(save_point="academic_proposal_advance")
			raise
		return self.status

	def record_stage(self, found, route):
		self.append("stage_resolutions", {**found, "stage": self.current_stage, "body_type": self.current_body_type})
		if found.decision == "Rejected":
			self.status = "Rejected"
		elif self.current_stage < len(route):
			self.current_stage += 1
			self.current_body_type = route[self.current_stage - 1]
		else:
			self.validate_ready_for_approval()
			proposal_approval.apply(self, self.proposal_type_doc, found.resolution_no)
			self.status, self.approved_on, self.approving_resolution = "Approved", found.resolution_date, found.resolution_no
		self.save_as_server()

	def save_as_server(self):
		"""Save status, stage and resolutions the server has just set (they are otherwise restored from the saved copy)."""
		self.flags.advancing = True
		try:
			self.save()
		finally:
			self.flags.advancing = False


def listed(doc, table):
	"""The batches or courses on `doc`, sorted."""
	field = "academic_year" if table == "batches" else "course"
	return sorted(row.get(field) for row in doc.get(table))
