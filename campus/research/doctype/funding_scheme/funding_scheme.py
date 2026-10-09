"""M08-01 Funding Scheme: an agency's scheme with its budget head template, overhead %, instalment pattern and UC
format. Whether a college can use it is campus.research.api.validate_scheme_usable."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class FundingScheme(Document):
	def validate(self):
		self.validate_heads()
		self.validate_percentages()

	def validate_heads(self):
		heads = [row.budget_head for row in self.heads]
		repeated = sorted({head for head in heads if heads.count(head) > 1})
		if repeated:
			frappe.throw(_("Budget heads {0} appear more than once.").format(", ".join(repeated)))

	def validate_percentages(self):
		if not 0 <= flt(self.overhead_percent) <= 100:
			frappe.throw(_("Overhead % must be between 0 and 100."))
		if any(flt(row.percent) <= 0 for row in self.instalments):
			frappe.throw(_("Each instalment must be a positive % of the sanction."))
		if sum(flt(row.percent) for row in self.instalments) > 100:
			frappe.throw(_("Instalments add up to more than 100% of the sanction."))
