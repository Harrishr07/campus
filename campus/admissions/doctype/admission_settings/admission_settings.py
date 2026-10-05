"""M04-01 Admission Settings: active admission year and the register / roll number patterns."""

from frappe.model.document import Document

from campus.admissions import numbers


class AdmissionSettings(Document):
	def validate(self):
		numbers.validate_pattern(self.register_no_pattern)
		if self.roll_no_pattern:
			numbers.validate_pattern(self.roll_no_pattern)
