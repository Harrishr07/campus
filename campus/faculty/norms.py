"""M07-01 Faculty Norm resolution: the version in force for a company on a date is the one with the latest
`effective_from` on or before that date."""

import frappe
from frappe.utils import getdate


def norm_in_force(company, on_date):
	"""Faculty Norm document in force for `company` on `on_date`, or None."""
	name = frappe.db.get_value(
		"Faculty Norm",
		{"company": company, "effective_from": ["<=", getdate(on_date)]},
		"name",
		order_by="effective_from desc",
	)
	return frappe.get_doc("Faculty Norm", name) if name else None


def cadre_rule(company, cadre, on_date):
	"""The Faculty Norm Cadre row for `cadre` in the norm in force, or None."""
	norm = norm_in_force(company, on_date)
	return next((row for row in norm.cadres if row.cadre == cadre), None) if norm else None
