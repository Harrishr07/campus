"""M02-02 Proposal Type: a kind of academic proposal (new course, syllabus revision, new elective, regulation change,
new programme) with the route of bodies it must pass, in order. Bodies are Body Types, so the route is data."""

import frappe
from frappe import _
from frappe.model.document import Document


class ProposalType(Document):
	def validate(self):
		bodies = [row.body_type for row in self.route]
		if not bodies:
			frappe.throw(_("A proposal type needs a route of at least one body."))
		repeated = sorted({b for b in bodies if bodies.count(b) > 1})
		if repeated:
			frappe.throw(_("A body can appear once in a route; repeated: {0}").format(", ".join(repeated)))
