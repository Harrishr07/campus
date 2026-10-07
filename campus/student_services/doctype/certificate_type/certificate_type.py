"""M05-04 Certificate Type: a kind of certificate the college issues, with its print format, fee and rules."""

from frappe.model.document import Document

from campus.student_services.certificates import validate_prefix


class CertificateType(Document):
	def validate(self):
		validate_prefix(self.number_prefix)
