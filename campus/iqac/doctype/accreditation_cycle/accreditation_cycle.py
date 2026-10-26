"""M01-02 / M01-03 Accreditation Cycle: one framework for one college (Company) and academic year; Metric Values hang off it.

Status: Collecting -> Validating -> IQAC Review (campus.iqac.cycle) -> Approved -> Submitted. Approved is reached only by the
final approval of the cycle through the approval engine (the policy's final action must be Submit): approving submits the
cycle and locks every Metric Value. Owners per criterion each get a task.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_platform.api import ApprovableDocument, find_policy, is_approved
from campus.iqac.cycle import assign_tasks
from campus.iqac.framework import status_of


class AccreditationCycle(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.validate_framework()
		self.validate_unique_cycle()
		self.validate_status()
		self.validate_owners()

	def validate_framework(self):
		if self.is_new() and status_of(self.framework) != "Published":
			frappe.throw(
				_("A cycle needs a Published framework; {0} is not published.").format(
					frappe.bold(self.framework)
				)
			)

	def validate_unique_cycle(self):
		if frappe.db.exists(
			"Accreditation Cycle",
			{
				"framework": self.framework, "company": self.company, "academic_year": self.academic_year,
				"name": ["!=", self.name],
			},
		):  # fmt: skip
			frappe.throw(
				_("{0} already has a cycle of {1} for {2}.").format(
					self.company, self.framework, self.academic_year
				)
			)

	def validate_status(self):
		self.status = self.status or "Collecting"
		if self.is_new() and self.status != "Collecting":
			frappe.throw(_("A new cycle starts as Collecting."))
		if not self.is_new() and self.has_value_changed("status") and not self.flags.cycle_transition:
			frappe.throw(_("Use Advance, Reopen and Request Approval to change the status of a cycle."))

	def validate_owners(self):
		seen = set()
		for row in self.owners:
			node = frappe.db.get_value(
				"Framework Node", row.criterion, ["framework", "node_type"], as_dict=True
			)
			if not node or node.framework != self.framework or node.node_type != "Criterion":
				frappe.throw(
					_("Row {0}: {1} is not a criterion of {2}.").format(
						row.idx, frappe.bold(row.criterion), self.framework
					)
				)
			if (row.criterion, row.user) in seen:
				frappe.throw(
					_("Row {0}: {1} is already an owner of {2}.").format(row.idx, row.user, row.criterion)
				)
			seen.add((row.criterion, row.user))

	def before_approval_request(self):
		"""Approval is for a cycle in IQAC Review, under a policy whose final action submits it."""
		if self.status != "IQAC Review":
			frappe.throw(
				_("Approval is requested for a cycle in IQAC Review; {0} is {1}.").format(
					self.name, _(self.status)
				)
			)
		policy = find_policy(self)
		if not policy:
			frappe.throw(
				_(
					"Set up an Approval Policy for Accreditation Cycle first; a cycle is approved only through it."
				)
			)
		if policy.on_final_action != "Submit":
			frappe.throw(
				_(
					"The final action of {0} must be Submit, so that approving the cycle submits and locks it."
				).format(frappe.bold(policy.name))
			)

	def before_submit(self):
		super().before_submit()
		if not is_approved(self) or self.status != "IQAC Review":
			frappe.throw(
				_("A cycle is submitted only by its approval, from IQAC Review."),
				title=_("Approval Required"),
			)

	def on_submit(self):
		from campus.iqac.cycle import lock_values

		self.db_set("status", "Approved")
		lock_values(self.name)

	def on_update(self):
		if self.docstatus == 0:
			assign_tasks(self)
