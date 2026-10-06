"""M15-01 Metric Value: the computed value of a Framework Node for a cycle, with its snapshot of inputs and records.

Created by the Compute action only (campus.iqac.compute); one per cycle and node, named {cycle}-{node code}.
"""

import frappe
from frappe.model.document import Document


class MetricValue(Document):
	def autoname(self):
		self.name = f"{self.cycle}-{frappe.db.get_value('Framework Node', self.node, 'code')}"
