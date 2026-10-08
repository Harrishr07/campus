"""M07-01 Faculty vs Sanctioned Posts (NAAC 2.4.1): sanctioned, filled and vacant posts per department and cadre."""

from frappe import _

from campus.faculty import staffing
from campus.faculty.report_scope import department_column, report_filters


def execute(filters=None):
	filters = report_filters(filters)
	if not filters:
		return columns(), []
	return columns(), staffing.faculty_vs_sanctioned(filters.company, filters.academic_year, filters.department)


def columns():
	return [
		department_column(),
		{"fieldname": "cadre", "label": _("Cadre"), "fieldtype": "Data", "width": 170},
		{"fieldname": "sanctioned", "label": _("Sanctioned"), "fieldtype": "Int", "width": 110},
		{"fieldname": "filled", "label": _("Filled"), "fieldtype": "Int", "width": 90},
		{"fieldname": "vacant", "label": _("Vacant"), "fieldtype": "Int", "width": 90},
	]
