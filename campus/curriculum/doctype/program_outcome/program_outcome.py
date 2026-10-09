"""M03-02 Program Outcome (PO1-PO12, seeded from the NBA graduate attributes) of a programme under a regulation."""

from frappe.model.document import Document

from campus.curriculum.outcomes import check_programme_regulation, normalise_code


class ProgramOutcome(Document):
	def autoname(self):
		self.po_code = normalise_code(self.po_code)
		self.name = f"{self.program}-{self.regulation}-{self.po_code}"

	def validate(self):
		check_programme_regulation(self.program, self.regulation)
