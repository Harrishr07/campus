"""M06-08 CIA Unlock Request: reopens the locked CIA marks of one offering until `unlock_until`.

Approved through the generic approval engine (seeded policy: the COE of the company); the final approval
submits it, and a submitted request whose window is still open lets the offering's CIA be edited
(campus.examinations.cia.lock_state). The request and the edits made under it show in the CIA Marks Audit Trail.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from campus.campus_platform.api import ApprovableDocument
from campus.examinations import cia


class CIAUnlockRequest(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		values = frappe.db.get_value(
			cia.SCHEDULE, self.cia_schedule, ["course_offering", "company", "entry_deadline"], as_dict=True
		)
		self.update(values)
		if self.docstatus == 0:  # an approval-driven submit must not re-judge the request
			self.check_window()

	def check_window(self):
		if cia.lock_state(self.cia_schedule) == cia.OPEN:
			frappe.throw(_("The CIA of {0} is still open for entry; no unlock is needed.").format(self.course_offering))
		if get_datetime(self.unlock_until) <= now_datetime():
			frappe.throw(_("Unlock Until must be in the future."))
