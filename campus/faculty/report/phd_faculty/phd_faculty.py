"""M07-01 PhD Faculty (NAAC 2.4.2): teachers and teachers with a PhD awarded by the year end, per department."""

from frappe import _
from frappe.utils import flt

from campus.faculty import staffing
from campus.faculty.report_scope import department_column, report_filters


def execute(filters=None):
	filters = report_filters(filters)
	if not filters:
		return columns(), []
	return columns(), data(filters)


def data(filters):
	by_department = {}
	for teacher in staffing.teachers(filters.company, filters.academic_year, filters.department):
		row = by_department.setdefault(
			teacher.department, {"department": teacher.department, "teachers": 0, "phd": 0}
		)
		row["teachers"] += 1
		row["phd"] += int(staffing.has_phd(teacher, filters.academic_year))
	rows = [by_department[d] for d in sorted(by_department, key=lambda d: d or "")]
	for row in rows:
		row["percent"] = flt(100 * row["phd"] / row["teachers"], 2)
	return rows


def columns():
	return [
		department_column(),
		{"fieldname": "teachers", "label": _("Full-time Teachers"), "fieldtype": "Int", "width": 140},
		{"fieldname": "phd", "label": _("With PhD"), "fieldtype": "Int", "width": 100},
		{"fieldname": "percent", "label": _("% With PhD"), "fieldtype": "Percent", "width": 110},
	]
