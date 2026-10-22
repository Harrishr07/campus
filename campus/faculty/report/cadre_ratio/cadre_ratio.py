"""M07-01 Cadre Ratio: per department, the teachers each cadre needs under the Faculty Norm in force at the year end
(students / student-faculty ratio, rounded up, split by the cadre ratio) against those on roll."""

from frappe import _

from campus.faculty import staffing
from campus.faculty.report_scope import department_column, report_filters


def execute(filters=None):
	filters = report_filters(filters)
	if not filters:
		return columns(), []
	return columns(), staffing.cadre_ratio(filters.company, filters.academic_year, filters.department)


def columns():
	return [
		department_column(),
		{"fieldname": "cadre", "label": _("Cadre"), "fieldtype": "Data", "width": 170},
		{"fieldname": "share", "label": _("Ratio Share"), "fieldtype": "Int", "width": 100},
		{"fieldname": "required", "label": _("Required"), "fieldtype": "Int", "width": 100},
		{"fieldname": "actual", "label": _("On Roll"), "fieldtype": "Int", "width": 90},
		{"fieldname": "shortfall", "label": _("Shortfall"), "fieldtype": "Int", "width": 90},
	]
