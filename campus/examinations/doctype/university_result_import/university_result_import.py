"""M06-10 University Result Import: the university's result file of an Affiliated Exam Session, previewed row by row
and written to the Student Results (campus.examinations.university_import). It is deleted only while it has written
nothing (before Importing); its preview rows go with it."""

from frappe.model.document import Document

from campus.examinations.university_import import trash_import, validate_import_doc


class UniversityResultImport(Document):
	def validate(self):
		validate_import_doc(self)

	def on_trash(self):
		trash_import(self)
