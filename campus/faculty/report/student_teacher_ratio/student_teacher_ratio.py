"""M07-01 Student-Teacher Ratio (NAAC 2.2.2): students of the year per full-time teacher, per department, against the
Faculty Norm's students-per-faculty figure."""

from frappe import _

from campus.faculty import staffing
from campus.faculty.report_scope import department_column, report_filters


def execute(filters=None):
	filters = report_filters(filters)
	if not filters:
		return columns(), []
	return columns(), staffing.student_teacher_ratio(
		filters.company, filters.academic_year, filters.department
	)


def columns():
	return [
		department_column(),
		{"fieldname": "students", "label": _("Students"), "fieldtype": "Int", "width": 100},
		{"fieldname": "teachers", "label": _("Full-time Teachers"), "fieldtype": "Int", "width": 140},
		{"fieldname": "ratio", "label": _("Students per Teacher"), "fieldtype": "Float", "width": 150},
		{"fieldname": "norm", "label": _("Norm"), "fieldtype": "Float", "width": 90},
	]
