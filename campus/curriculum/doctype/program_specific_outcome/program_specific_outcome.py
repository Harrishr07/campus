"""M03-02 Program Specific Outcome (PSO1 ...) of a programme under a regulation."""

from frappe.model.document import Document

from campus.curriculum.outcomes import check_programme_regulation, normalise_code


class ProgramSpecificOutcome(Document):
	def autoname(self):
		self.pso_code = normalise_code(self.pso_code)
		self.name = f"{self.program}-{self.regulation}-{self.pso_code}"

	def validate(self):
		check_programme_regulation(self.program, self.regulation)
