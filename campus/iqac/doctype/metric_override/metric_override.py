"""M01-03 Metric Override: a request to replace a computed Metric Value by a manual one, with a reason.

Goes through the approval engine (seeded policy: the IQAC Coordinator of the company; the requester and owner never approve).
Only the final approval submits it, and only then does the manual value become the effective one; until then, and when it
is rejected, the computed value stays effective. Cancelling an applied override restores the computed value.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.campus_platform.api import ApprovableDocument, is_approved
from campus.iqac.access import may_edit
from campus.iqac.cycle import CLOSED_CYCLE

OPEN_STATUSES = ("Draft", "Computed")


class MetricOverride(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		if self.docstatus == 0:
			self.set_context()
			self.check_may_request()
			self.check_applicable()

	def before_submit(self):
		super().before_submit()
		if not is_approved(self):  # without a policy the engine would submit directly: an override always needs one
			frappe.throw(
				_("A Metric Override is submitted only by its approval. Set up an Approval Policy for Metric Override."),
				title=_("Approval Required"),
			)
		self.check_applicable()

	def on_submit(self):
		metric = self.metric(lock=True)
		metric.flags.override_applied = True
		metric.update(
			{"manual_value": self.proposed_value, "override_reason": self.reason, "override_approved": 1, "override_request": self.name}
		)
		metric.save(ignore_permissions=True)

	def on_cancel(self):
		metric = self.metric(lock=True)
		if metric.override_request != self.name:
			return  # a later override replaced it
		self.check_applicable(applied=True)
		metric.flags.override_applied = True
		metric.update({"manual_value": None, "override_reason": None, "override_approved": 0, "override_request": None})
		metric.save(ignore_permissions=True)

	def metric(self, lock=False):
		return frappe.get_doc("Metric Value", self.metric_value, for_update=lock)

	def set_context(self):
		values = frappe.db.get_value("Metric Value", self.metric_value, ["cycle", "company", "computed_value"], as_dict=True)
		if not values:
			frappe.throw(_("Metric Value {0} does not exist.").format(frappe.bold(self.metric_value)))
		self.update(values)
		self.reason = (self.reason or "").strip()
		if not self.reason:
			frappe.throw(_("An override needs a reason."))

	def check_may_request(self):
		node = frappe.db.get_value("Metric Value", self.metric_value, "node")
		if not may_edit(frappe.session.user, self.cycle, node):
			frappe.throw(_("Only IQAC staff or the owner of the criterion can override {0}.").format(self.metric_value), frappe.PermissionError)

	def check_applicable(self, applied=False):
		"""The override can be requested, approved or (applied=True) withdrawn only while the value is open."""
		metric = self.metric(lock=True)
		if frappe.db.get_value("Accreditation Cycle", metric.cycle, "status") in CLOSED_CYCLE:
			frappe.throw(_("The cycle of {0} is approved; its values are locked.").format(frappe.bold(metric.name)))
		if not frappe.db.get_value("Framework Node", metric.node, "formula"):
			frappe.throw(_("{0} has no formula; enter its value directly instead of overriding it.").format(frappe.bold(metric.name)))
		if metric.status not in OPEN_STATUSES and not applied:
			frappe.throw(_("{0} is {1}; reopen it before an override.").format(frappe.bold(metric.name), _(metric.status)))
