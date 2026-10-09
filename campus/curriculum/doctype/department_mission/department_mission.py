"""M03-02 Department Mission: one numbered mission statement (M1, M2 ...) of a department, which PEOs map to."""

from frappe.model.document import Document

from campus.curriculum.outcomes import normalise_code


class DepartmentMission(Document):
	def autoname(self):
		self.mission_code = normalise_code(self.mission_code)
		self.name = f"{self.department}-{self.mission_code}"
