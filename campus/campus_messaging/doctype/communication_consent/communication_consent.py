"""M16-02 Communication Consent: opt-in/out per party, channel and purpose."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class CommunicationConsent(Document):
	def autoname(self):
		"""One row per (party, channel, purpose): the primary key makes duplicates impossible even under races."""
		self.name = f"{self.party_type}-{self.party}-{self.channel}-{self.purpose}"[:140]

	def validate(self):
		duplicate = frappe.db.exists(
			"Communication Consent",
			{
				"party_type": self.party_type,
				"party": self.party,
				"channel": self.channel,
				"purpose": self.purpose,
				"name": ("!=", self.name),
			},
		)
		if duplicate:
			frappe.throw(_("A consent record already exists for this party, channel and purpose: {0}").format(duplicate))
		if self.is_new() or self.has_value_changed("status"):
			self.timestamp = now_datetime()
