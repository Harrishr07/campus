"""M07-01 Sanctioned Post: the sanctioned strength of one cadre in a department for an academic year (NAAC 2.4.1).
The name is department + cadre + year, so the primary key keeps one record per combination."""

from frappe.model.document import Document


class SanctionedPost(Document):
	def autoname(self):
		self.name = f"{self.department} - {self.cadre} - {self.academic_year}"
