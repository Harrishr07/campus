"""M06-10 University Exam Format: how a university's exam files look - direction (Export: our registrations and CIA;
Import: its results), file type, header row, date format, the ordered columns (heading -> our source) and the code
mappings between our codes and the university's (campus.examinations.university_files). The official formats are the
university's; the seeded ones are placeholders to replace."""

from frappe.model.document import Document

from campus.examinations.university_files import validate_format


class UniversityExamFormat(Document):
	def validate(self):
		validate_format(self)
