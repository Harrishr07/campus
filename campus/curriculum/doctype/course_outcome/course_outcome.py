"""M03-02 Course Outcome: the canonical CO (code, statement, Bloom level) of a course in one curriculum version.

The code is what CIA questions, question bank items and feedback questions tag; it cannot change once saved.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.curriculum.outcomes import normalise_code


class CourseOutcome(Document):
	def autoname(self):
		self.co_code = normalise_code(self.co_code)
		self.name = f"{self.curriculum}-{self.course}-{self.co_code}"

	def validate(self):
		self.co_code = normalise_code(self.co_code)
		curriculum = frappe.db.get_value("Curriculum", self.curriculum, ["program", "regulation"], as_dict=True)
		self.program, self.regulation = curriculum.program, curriculum.regulation
		self.company = frappe.db.get_value("Program", self.program, "oc_company")
		if not frappe.db.exists("Curriculum Course", {"parent": self.curriculum, "parenttype": "Curriculum", "course": self.course}):
			frappe.throw(_("{0} is not a course of curriculum {1}.").format(frappe.bold(self.course), frappe.bold(self.curriculum)))
		filters = {"course": self.course, "curriculum": self.curriculum, "co_code": self.co_code}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Course Outcome", filters):
			frappe.throw(_("{0} already has {1} in {2}.").format(frappe.bold(self.course), frappe.bold(self.co_code), frappe.bold(self.curriculum)))
