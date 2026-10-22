"""M06-10 University Exam Format: how a university's exam files look - direction (Export: our registrations and CIA;
Import: its results), file type, header row, date format, the ordered columns (heading -> our source) and the code
mappings between our codes and the university's (campus.examinations.university_files). The official formats are the
university's; the seeded ones are placeholders to replace. A format belongs to one college (company, scoped by User
Permissions); a blank company means shared by every college, which only a System Manager edits."""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.examinations.university_files import validate_format


class UniversityExamFormat(Document):
	def validate(self):
		if not self.company and "System Manager" not in frappe.get_roles():
			frappe.throw(_("Give the format its college (Company): a shared format is edited by a System Manager only."))
		validate_format(self)
