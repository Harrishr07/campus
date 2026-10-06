"""M15-01 Framework Node: criterion, key indicator or metric of a framework; a metric's formula runs over data points."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.iqac.formula import validate_formula


class FrameworkNode(Document):
	def validate(self):
		self.validate_parent()
		if self.node_type == "Metric":
			if not self.formula:
				frappe.throw(_("A Metric needs a formula."))
			validate_formula(self.formula)
		elif self.formula:
			frappe.throw(_("Only a Metric has a formula."))

	def validate_parent(self):
		if self.parent_node and frappe.db.get_value("Framework Node", self.parent_node, "framework") != self.framework:
			frappe.throw(_("The parent node belongs to another framework."))
