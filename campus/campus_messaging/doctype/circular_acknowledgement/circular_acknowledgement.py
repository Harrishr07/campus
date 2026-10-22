"""M16-03 Circular Acknowledgement: one row per (circular, user), created by circulars.acknowledge."""

from frappe.model.document import Document


class CircularAcknowledgement(Document):
	def autoname(self):
		"""The name is the primary key, so a user cannot acknowledge a circular twice even under races."""
		self.name = f"{self.circular}-{self.user}"[:140]
