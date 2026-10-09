"""M17-06 / AQAR 2.5.1 Days Exam End to Result: per published exam session of the company in the academic year,
the last exam (exam_end, else the last scheduled exam), the publication time and the days between; the total row
is their average, the days_exam_to_result data point (campus.examinations.coe_reports). Sessions without both
dates are left out.

Limited to the companies the user is permitted for and to the exam sessions the user may read."""

import frappe
from frappe import _

from campus.examinations import coe_report_rules as rules
from campus.examinations import coe_reports


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters) if coe_reports.in_scope(filters.company) else []


def columns():
	return [
		{"fieldname": "exam_session", "label": _("Exam Session"), "fieldtype": "Data", "width": 160},  # Data: the Average row
		{"fieldname": "exam_end", "label": _("Last Exam"), "fieldtype": "Date", "width": 120},
		{"fieldname": "publish_at", "label": _("Published At"), "fieldtype": "Datetime", "width": 170},
		{"fieldname": "days", "label": _("Days"), "fieldtype": "Float", "precision": 2, "width": 100},
	]  # fmt: skip


def data(filters):
	rows = coe_reports.year_session_days(filters.company, filters.academic_year, lister=frappe.get_list)
	if rows:
		rows.append({"exam_session": _("Average"), "days": rules.average([r.days for r in rows])})
	return rows
