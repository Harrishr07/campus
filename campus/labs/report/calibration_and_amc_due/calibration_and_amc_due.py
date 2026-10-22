"""M12-05 Calibration and AMC Due: maintenance tasks of lab equipment due within the window (overdue ones included),
limited to the companies the user may read."""

import frappe
from frappe import _

from campus.labs.report_scope import scoped_companies
from campus.labs.calibration import due_tasks, notice_days


def execute(filters=None):
	filters = frappe._dict(filters or {})
	within = notice_days() if filters.within_days in (None, "") else filters.within_days
	rows = due_tasks(within, filters.as_on, filters.maintenance_type, scoped_companies(filters.company), filters.laboratory)
	return columns(), rows


def columns():
	return [
		{"fieldname": "laboratory", "label": _("Laboratory"), "fieldtype": "Link", "options": "Laboratory", "width": 170},
		{"fieldname": "asset", "label": _("Asset"), "fieldtype": "Link", "options": "Asset", "width": 130},
		{"fieldname": "asset_name", "label": _("Equipment"), "fieldtype": "Data", "width": 180},
		{"fieldname": "task", "label": _("Task"), "fieldtype": "Data", "width": 180},
		{"fieldname": "maintenance_type", "label": _("Type"), "fieldtype": "Data", "width": 140},
		{"fieldname": "periodicity", "label": _("Periodicity"), "fieldtype": "Data", "width": 100},
		{"fieldname": "next_due_date", "label": _("Due"), "fieldtype": "Date", "width": 100},
		{"fieldname": "days_left", "label": _("Days Left"), "fieldtype": "Int", "width": 90},
		{"fieldname": "in_charge", "label": _("In-charge"), "fieldtype": "Link", "options": "Employee", "width": 120},
		{"fieldname": "maintenance", "label": _("Asset Maintenance"), "fieldtype": "Link", "options": "Asset Maintenance", "width": 150},
	]  # fmt: skip
