"""M02-01 Body Type: a kind of statutory or institutional body (term, meetings per year, quorum percentage and
the required composition by member category). The rule values are records, so a regulation change is data."""

import frappe
from frappe import _
from frappe.model.document import Document


class BodyType(Document):
	def validate(self):
		self.validate_rules()

	def validate_rules(self):
		categories = [row.category for row in self.composition]
		repeated = sorted({c for c in categories if categories.count(c) > 1})
		if repeated:
			frappe.throw(_("Each member category can have one composition rule; repeated: {0}").format(", ".join(map(_, repeated))))
		for row in self.composition:
			if row.maximum_count and row.maximum_count < row.minimum_count:
				frappe.throw(_("Row {0}: Maximum {1} cannot be below Minimum {2}").format(row.idx, row.maximum_count, row.minimum_count))
			if row.mandatory_for_quorum and not row.minimum_count:
				frappe.throw(_("Row {0}: a category mandatory for quorum needs a Minimum of at least 1").format(row.idx))
