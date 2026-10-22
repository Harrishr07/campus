"""M14-02 Round Result: the shortlist of one round of a drive. Only students with a live Drive Registration for the
drive can be listed, each once. Rows can be loaded in bulk from a file (campus.placement.round_upload)."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.placement.api import registered_students


class RoundResult(Document):
	def validate(self):
		drive = frappe.get_doc("Placement Drive", self.drive)
		if drive.status in ("Draft", "Cancelled"):
			frappe.throw(_("{0} is {1}; round results can be entered once it is open").format(self.drive, _(drive.status)))
		round_row = next((row for row in drive.rounds if row.round_no == self.round_no), None)
		if not round_row:
			frappe.throw(_("{0} has no round {1}").format(self.drive, self.round_no))
		self.round_name, self.company = round_row.round_name, drive.company
		self.check_students()

	def check_students(self):
		registered = set(registered_students(self.drive))
		seen = set()
		for row in self.results:
			if row.student not in registered:
				frappe.throw(_("Row {0}: {1} is not registered for {2}").format(row.idx, row.student, self.drive))
			if row.student in seen:
				frappe.throw(_("Row {0}: {1} is listed twice").format(row.idx, row.student))
			seen.add(row.student)
