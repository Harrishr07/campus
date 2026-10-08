"""M07-01 Teaching Experience (NAAC 2.4.3): each teacher's years of experience in this institution at the year end,
with the average in the summary."""

from frappe import _
from frappe.utils import flt

from campus.faculty import staffing
from campus.faculty.report_scope import department_column, report_filters


def execute(filters=None):
	filters = report_filters(filters)
	if not filters:
		return columns(), []
	rows = data(filters)
	return columns(), rows, data_issues(filters), None, summary(rows)


def data(filters):
	return [
		{"employee": t.name, "employee_name": t.employee_name, "department": t.department, "cadre": t.oc_cadre,
			"date_of_joining": t.date_of_joining, "years": staffing.experience_years(t, filters.academic_year)}
		for t in staffing.teachers(filters.company, filters.academic_year, filters.department)
	]  # fmt: skip


def data_issues(filters):
	left = staffing.left_without_relieving_date(filters.company, filters.academic_year, filters.department)
	if not left:
		return None
	names = ", ".join(f"{e.name} ({e.employee_name})" for e in left)
	return _("Not counted, marked Left with no relieving date: {0}").format(names)


def summary(rows):
	average = flt(sum(r["years"] for r in rows) / len(rows), 2) if rows else 0
	return [
		{"value": len(rows), "label": _("Full-time Teachers"), "datatype": "Int"},
		{"value": average, "label": _("Average Experience (Years)"), "datatype": "Float"},
	]


def columns():
	return [
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 130},
		{"fieldname": "employee_name", "label": _("Name"), "fieldtype": "Data", "width": 180},
		department_column(),
		{"fieldname": "cadre", "label": _("Cadre"), "fieldtype": "Data", "width": 160},
		{"fieldname": "date_of_joining", "label": _("Joined"), "fieldtype": "Date", "width": 110},
		{"fieldname": "years", "label": _("Experience (Years)"), "fieldtype": "Float", "precision": 1, "width": 140},
	]
