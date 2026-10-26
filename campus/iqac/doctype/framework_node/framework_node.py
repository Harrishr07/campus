"""M01-02 Framework Node: criterion, key indicator, metric, sub-metric or extended profile item of a framework.

A metric's formula runs over data points; a metric without one is answered by hand in the declared answer type.
Nodes of a Published or Retired framework are locked (campus.iqac.framework).
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.iqac.formula import dependents, validate_formula
from campus.iqac.framework import assert_editable

PARENT_TYPE = {
	"Key Indicator": "Criterion",
	"Metric": "Key Indicator",
	"Sub-Metric": "Metric",
}  # roots are not listed


class FrameworkNode(Document):
	def validate(self):
		assert_editable(self.framework)
		self.validate_parent()
		self.validate_formula()
		self.validate_answer()

	def on_trash(self):
		assert_editable(self.framework)
		self.check_not_used()

	def validate_parent(self):
		if not self.parent_node:
			if self.node_type in PARENT_TYPE:
				frappe.throw(_("A {0} needs a parent node.").format(_(self.node_type)))
			return
		parent_framework, parent_type = frappe.db.get_value(
			"Framework Node", self.parent_node, ["framework", "node_type"]
		)
		if parent_framework != self.framework:
			frappe.throw(_("The parent node belongs to another framework."))
		if parent_type != PARENT_TYPE.get(self.node_type):
			frappe.throw(_("A {0} cannot sit under a {1}.").format(_(self.node_type), _(parent_type)))

	def validate_formula(self):
		if self.formula and self.node_type != "Metric":
			frappe.throw(_("Only a Metric has a formula."))
		if self.formula:
			validate_formula(
				self.formula, self.framework, self.code, check_nodes=not self.flags.skip_node_references
			)
		elif not self.is_new() and self.get_doc_before_save().formula:
			self.check_not_used()

	def check_not_used(self):
		users = dependents(self.framework, self.code)
		if users:
			frappe.throw(
				_("Node {0} is used in the formula of {1}.").format(frappe.bold(self.code), ", ".join(users))
			)

	def validate_answer(self):
		if self.answer_type == "Choice" and not (self.choices or "").strip():
			frappe.throw(_("A Choice answer needs its choices."))
		if self.word_limit and self.answer_type != "Narrative":
			frappe.throw(_("A word limit applies to Narrative answers only."))
