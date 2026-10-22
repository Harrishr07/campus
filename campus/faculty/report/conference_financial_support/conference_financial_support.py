"""M07-05 Conference Financial Support (NAAC 6.3.2): verified Conference and Membership achievements of the academic year
that the institution supported with money, one row per achievement, with the amount."""

from frappe import _

from campus.faculty import development
from campus.faculty.report_scope import department_column, report_filters


def execute(filters=None):
	filters = report_filters(filters)
	if not filters:
		return columns(), []
	return columns(), development.supported_achievements(filters.company, filters.academic_year, filters.department)


def columns():
	return [
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 130},
		{"fieldname": "employee_name", "label": _("Name"), "fieldtype": "Data", "width": 170},
		department_column(),
		{"fieldname": "achievement_type", "label": _("Type"), "fieldtype": "Data", "width": 110},
		{"fieldname": "title", "label": _("Conference / Body"), "fieldtype": "Data", "width": 240},
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "amount", "label": _("Support Amount"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "name", "label": _("Achievement"), "fieldtype": "Link", "options": "Faculty Achievement", "width": 150},
	]
