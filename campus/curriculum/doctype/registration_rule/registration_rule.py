"""M03-04 Registration Rule: the semester registration limits of a regulation (credits, drop, add, electives).

One record per Regulation, so `get_rule(student, "Registration Rule")` resolves it.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from campus.curriculum.registration_rules import TYPES, excluded_types


class RegistrationRule(Document):
	def validate(self):
		unknown = excluded_types(self.excluded_types) - set(TYPES)
		if unknown:
			frappe.throw(_("Unknown registration types: {0}.").format(", ".join(sorted(unknown))))
		numbers = (
			self.max_credits_per_semester, self.max_drop_credits, self.drop_window_days,
			self.add_from_semester, self.max_add_credits, self.max_add_courses, self.elective_min_enrolment,
		)  # fmt: skip
		if min(flt(n) for n in numbers) < 0:
			frappe.throw(_("Registration limits cannot be negative."))
		if cint(self.add_from_semester) < 0:
			frappe.throw(_("Additional courses cannot start before semester 1."))
