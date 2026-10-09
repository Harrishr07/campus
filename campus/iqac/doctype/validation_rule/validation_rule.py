"""M01-03 Validation Rule: a check on the answers of a framework, kept as a record (never as code).

Rule types: Required Evidence (a slot of the node has evidence), Word Limit (narrative within the limit), Comparison
(the node's value against another node's; each side sums the node's answered values, college and department rows), Range (value within minimum / maximum), Non-empty (the node is answered).
Blocking failures stop a cycle moving to IQAC Review; warnings need a comment. Evaluated by campus.iqac.validation.
"""

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class ValidationRule(Document):
	def validate(self):
		self.validate_nodes()
		getattr(self, CHECKS[self.rule_type])()

	def validate_nodes(self):
		for field in ("node", "compare_node"):
			node = self.get(field)
			if node and frappe.db.get_value("Framework Node", node, "framework") != self.framework:
				frappe.throw(_("{0} is not a node of {1}.").format(frappe.bold(node), frappe.bold(self.framework)))

	def validate_comparison(self):
		if not (self.compare_node and self.operator):
			frappe.throw(_("A Comparison rule needs the node to compare with and an operator."))

	def validate_range(self):
		"""Bounds are kept as text so that a blank (no bound) differs from a 0 bound."""
		for field in ("minimum", "maximum"):
			text = str(self.get(field) if self.get(field) is not None else "").strip()
			if text and not is_number(text):
				frappe.throw(_("{0} must be a number.").format(self.meta.get_label(field)))
			self.set(field, text or None)
		if self.minimum is None and self.maximum is None:
			frappe.throw(_("A Range rule needs a minimum, a maximum or both."))
		if self.minimum is not None and self.maximum is not None and flt(self.minimum) > flt(self.maximum):
			frappe.throw(_("Minimum cannot be above Maximum."))

	def validate_word_limit(self):
		if not (self.limit or frappe.db.get_value("Framework Node", self.node, "word_limit")):
			frappe.throw(_("A Word Limit rule needs a limit; neither the rule nor the node has one."))

	def validate_other(self):
		pass


def is_number(text):
	"""True for a finite number written as text (nan and inf are not bounds)."""
	try:
		return math.isfinite(float(text))
	except ValueError:
		return False


CHECKS = {
	"Comparison": "validate_comparison", "Range": "validate_range", "Word Limit": "validate_word_limit",
	"Required Evidence": "validate_other", "Non-empty": "validate_other",
}  # fmt: skip
