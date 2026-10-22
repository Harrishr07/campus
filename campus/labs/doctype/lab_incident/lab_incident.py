"""M12-05 Lab Incident: an accident or near miss in a laboratory, kept until it is closed with the action taken."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime, today


class LabIncident(Document):
	def validate(self):
		if get_datetime(self.incident_time) > now_datetime():
			frappe.throw(_("The incident time cannot be in the future."))
		if self.status == "Closed":
			if not self.action_taken:
				frappe.throw(_("Record the action taken before closing the incident."))
			self.closed_on = self.closed_on or today()
		else:
			self.closed_on = None
