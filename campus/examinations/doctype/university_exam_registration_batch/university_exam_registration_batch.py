"""M06-10 University Exam Registration Batch: the registrations and CIA of an Affiliated Exam Session exported to the
university, with the transmission and acknowledgement references and per-row rejections
(campus.examinations.university_export)."""

from frappe.model.document import Document

from campus.examinations.university_export import validate_batch


class UniversityExamRegistrationBatch(Document):
	def validate(self):
		validate_batch(self)
