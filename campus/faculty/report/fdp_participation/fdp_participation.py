"""M07-05 FDP Participation (NAAC 6.3.4): teachers present at a Faculty Development Programme (HRMS Training Event flagged as
an FDP) that started in the academic year, one row per teacher per FDP, from the Training Event itself."""

from frappe import _

from campus.faculty import development
from campus.faculty.report_scope import department_column, report_filters


def execute(filters=None):
	filters = report_filters(filters)
	if not filters:
		return columns(), []
	return columns(), development.fdp_attendances(filters.company, filters.academic_year, filters.department)


def columns():
	return [
		{
			"fieldname": "employee",
			"label": _("Employee"),
			"fieldtype": "Link",
			"options": "Employee",
			"width": 130,
		},
		{"fieldname": "employee_name", "label": _("Name"), "fieldtype": "Data", "width": 170},
		department_column(),
		{
			"fieldname": "training_event",
			"label": _("FDP"),
			"fieldtype": "Link",
			"options": "Training Event",
			"width": 220,
		},
		{"fieldname": "start_time", "label": _("From"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "end_time", "label": _("To"), "fieldtype": "Datetime", "width": 150},
	]
