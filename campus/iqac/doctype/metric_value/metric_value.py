"""M01-02 / M01-03 Metric Value: the value of a Framework Node for a cycle (and, for department-wise nodes, a department).

Computed values come from the Compute actions (campus.iqac.compute) with their snapshot of inputs and records; a node
without a formula is answered by hand (manual value, choice or narrative). A computed value is replaced only through an
approved Metric Override. One per cycle, node and department, named {cycle}-{node code}[-{department}].
Status: Draft / Computed / Verified / Locked (see campus.iqac.metric_values); a closed cycle's values are locked.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from campus.iqac.cycle import CLOSED_CYCLE
from campus.iqac.metric_values import FROZEN, count_words, effective_value

OVERRIDE_FIELDS = ("override_reason", "override_approved", "override_request")
ENGINE_FIELDS = (
	"computed_value",
	"computed_at",
	"snapshot",
	"recomputed_value",
	"source_changed",
	"verified_by",
	"verified_on",
)
ANSWER_FIELDS = ("manual_value", "choice", "narrative")
NODE_FIELDS = ["framework", "code", "node_type", "answer_type", "choices", "formula", "department_wise"]


class MetricValue(Document):
	def autoname(self):
		code = frappe.db.get_value("Framework Node", self.node, "code")
		self.name = f"{self.cycle}-{code}" + (f"-{self.department}" if self.department else "")

	def validate(self):
		node = frappe.db.get_value("Framework Node", self.node, NODE_FIELDS, as_dict=True)
		cycle = frappe.db.get_value(
			"Accreditation Cycle", self.cycle, ["framework", "company", "status"], as_dict=True
		)
		self.validate_scope(node, cycle)
		self.validate_not_frozen()
		self.validate_engine_fields()
		self.validate_answer(node)
		self.validate_override_fields(node)
		self.word_count = count_words(self.narrative)
		self.answered = int(self.has_answer(node))
		self.value = effective_value(
			bool(node.formula), flt(self.computed_value), flt(self.manual_value), self.override_approved
		)
		self.refresh_status()

	def validate_scope(self, node, cycle):
		if node.framework != cycle.framework:
			frappe.throw(_("{0} is not a node of the cycle's framework.").format(frappe.bold(self.node)))
		if cycle.status in CLOSED_CYCLE:
			frappe.throw(
				_("{0} is {1}; its values are locked.").format(frappe.bold(self.cycle), _(cycle.status))
			)
		if self.department:
			if not node.department_wise:
				frappe.throw(_("{0} is not answered department-wise.").format(frappe.bold(self.node)))
			if frappe.db.get_value("Department", self.department, "company") != cycle.company:
				frappe.throw(
					_("Department {0} does not belong to {1}.").format(
						frappe.bold(self.department), cycle.company
					)
				)

	def validate_not_frozen(self):
		before = self.get_doc_before_save()
		if before and before.status == "Locked":
			frappe.throw(_("{0} is Locked and cannot be changed.").format(frappe.bold(self.name)))
		if (
			self.has_value_changed("status")
			and not self.flags.status_change
			and (self.status in FROZEN or (before and before.status in FROZEN))
		):
			frappe.throw(_("Use Verify and Reopen to change the status of a value."))
		if (
			before
			and before.status == "Verified"
			and not self.flags.status_change
			and any(self.changed(field) for field in (*ANSWER_FIELDS, *OVERRIDE_FIELDS))
		):
			frappe.throw(_("{0} is Verified; reopen it to change the answer.").format(frappe.bold(self.name)))

	def validate_engine_fields(self):
		"""read_only is UI-only: the engine's fields change only through compute, Verify / Reopen and an applied override."""
		if self.flags.engine_write or self.flags.override_applied:
			return
		if self.is_new():
			changed = any(self.get(field) not in (None, "", 0) for field in ENGINE_FIELDS)
		else:
			before = (
				self.get_doc_before_save()
			)  # a blank, a None and a zero are the same "unset" in a NOT NULL column
			changed = any((before.get(field) or None) != (self.get(field) or None) for field in ENGINE_FIELDS)
		if changed:
			frappe.throw(
				_(
					"The computed value, its snapshot and the verification are set by the engine and cannot be edited."
				)
			)

	def validate_answer(self, node):
		if node.node_type not in ("Metric", "Sub-Metric", "Extended Profile"):
			frappe.throw(_("{0} takes no answer.").format(frappe.bold(self.node)))
		numeric = node.answer_type in ("Number", "Percent")
		for field, allowed in (
			("manual_value", numeric),
			("choice", node.answer_type == "Choice"),
			("narrative", node.answer_type == "Narrative"),
		):
			if self.get(field) not in (None, "", 0) and not allowed:
				frappe.throw(
					_("{0} cannot take {1}: its answer type is {2}.").format(
						frappe.bold(self.node), self.meta.get_label(field), _(node.answer_type or "none")
					)
				)
		if self.choice and self.choice not in (node.choices or "").splitlines():
			frappe.throw(
				_("{0} is not one of the choices of {1}.").format(
					frappe.bold(self.choice), frappe.bold(self.node)
				)
			)

	def validate_override_fields(self, node):
		"""A computed node's manual value and the override fields change only when an approved Metric Override is applied."""
		guarded = (*OVERRIDE_FIELDS, *(("manual_value",) if node.formula else ()))
		if not self.flags.override_applied and any(self.changed(field) for field in guarded):
			frappe.throw(
				_("A computed value is changed only by an approved Metric Override; use Request Override.")
			)

	def has_answer(self, node):
		"""A computed node is answered once computed; a number by a non-zero value or when ticked (a zero); text by its text."""
		if node.formula:
			return bool(self.computed_at)
		return bool(
			self.manual_value
			or self.choice
			or count_words(self.narrative)
			or (self.answered and node.answer_type in ("Number", "Percent"))
		)

	def changed(self, field):
		"""True when `field` differs from the saved value (a blank counts as unset, a Check as 0 or 1)."""
		before = self.get_doc_before_save()
		old, new = (before.get(field) if before else None), self.get(field)
		if field == "override_approved":
			return int(old or 0) != int(new or 0)
		return (None if old == "" else old) != (None if new == "" else new)

	def refresh_status(self):
		if self.status not in FROZEN:
			self.status = "Computed" if self.computed_at else "Draft"
