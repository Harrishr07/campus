"""M05-11 Student Correction Settings: the Student fields locked against direct edit and the role that may override."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.student_services import correction_rules as rules


class StudentCorrectionSettings(Document):
	def validate(self):
		listed = [
			line.strip()
			for line in (self.locked_fields or "").replace(",", "\n").splitlines()
			if line.strip()
		]
		unknown = [name for name in listed if name not in rules.student_fields()]
		if unknown:
			frappe.throw(
				_("These fields have no correction workflow and cannot be locked: {0}").format(
					", ".join(unknown)
				)
			)
