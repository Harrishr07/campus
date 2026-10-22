"""M06-10 University Result Import: the university's result file of an Affiliated Exam Session, previewed row by row
and written to the Student Results (campus.examinations.university_import)."""

from frappe.model.document import Document

from campus.examinations.university_import import validate_import_doc


class UniversityResultImport(Document):
	def validate(self):
		validate_import_doc(self)
