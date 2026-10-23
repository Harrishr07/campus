"""M01-08 Official Document Setting: the days before expiry on which the Principal and the IQAC Coordinator are alerted."""

import frappe
from frappe.model.document import Document

from campus.iqac import official_documents as register


class OfficialDocumentSetting(Document):
	def validate(self):
		register.alert_offsets(self.alert_days)  # refuses anything but whole numbers
