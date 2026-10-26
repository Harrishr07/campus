"""M12-05 Calibration and AMC due list and the daily calibration notice.

Equipment is an Asset whose Location is its laboratory's Asset Location. Calibrations and AMC visits are the tasks of the
asset's Asset Maintenance: type Calibration, or Preventive Maintenance for an AMC visit; ERPNext moves a task's next due
date when its Asset Maintenance Log is completed. Each calibration due within the notice days of Laboratory Settings
(15 by default) is sent to the lab in-charge once per due date, by the daily run.
"""

import frappe
from frappe.query_builder import DocType
from frappe.utils import add_days, getdate, today

from campus.campus_messaging.api import send
from campus.labs.rules import days_left, notice_due

EVENT = "lab.calibration_due"
CALIBRATION = "Calibration"
DEFAULT_NOTICE_DAYS = 15  # the default of the setting record, for a site that never saved it
RETIRED_STATUSES = ("Scrapped", "Sold")


def notice_days():
	value = frappe.db.get_single_value("Laboratory Settings", "calibration_notice_days")
	return int(value or DEFAULT_NOTICE_DAYS)  # an unsaved setting reads as 0


def due_tasks(within_days, on_date=None, maintenance_type=None, companies=None, laboratory=None):
	"""Open maintenance tasks of lab equipment due on or before `on_date` + `within_days` (overdue ones too), earliest first.

	`companies` limits the labs' colleges (None = all, [] = none). Tasks of an asset of another company than its lab are left out.
	"""
	if companies is not None and not companies:
		return []
	on_date = getdate(on_date or today())
	maintenance, task, asset, lab = (
		DocType(n) for n in ("Asset Maintenance", "Asset Maintenance Task", "Asset", "Laboratory")
	)
	query = (
		frappe.qb.from_(task)
		.join(maintenance).on(task.parent == maintenance.name)
		.join(asset).on(maintenance.asset_name == asset.name)
		.join(lab).on((lab.asset_location == asset.location) & (lab.company == asset.company))
		.select(
			maintenance.name.as_("maintenance"), task.name.as_("task_name"), task.maintenance_task.as_("task"),
			task.maintenance_type, task.periodicity, task.next_due_date, asset.name.as_("asset"),
			asset.asset_name, lab.name.as_("laboratory"), lab.company, lab.in_charge,
		)
		.where(task.maintenance_status != "Cancelled")
		.where(task.next_due_date <= add_days(on_date, int(within_days)))
		.where(asset.status.notin(RETIRED_STATUSES))
		.where(asset.docstatus < 2)
		.where(lab.disabled == 0)
		.orderby(task.next_due_date)
		.orderby(task.name)
	)  # fmt: skip
	if maintenance_type:
		query = query.where(task.maintenance_type == maintenance_type)
	if companies is not None:
		query = query.where(lab.company.isin(companies))
	if laboratory:
		query = query.where(lab.name == laboratory)
	rows = query.run(as_dict=True)
	for row in rows:
		row["days_left"] = days_left(row.next_due_date, on_date)
	return rows


def send_calibration_notices(on_date=None):
	"""Scheduler entry point (daily). Returns the number of calibrations notified about."""
	on_date = getdate(on_date or today())
	days = notice_days()
	count = 0
	for row in due_tasks(days, on_date, CALIBRATION):
		if not notice_due(row.next_due_date, on_date, days):
			continue  # overdue: it stays on the due report
		try:
			notify(row)
			count += 1
		except Exception:
			frappe.log_error(
				title=f"Calibration notice failed for {row.asset}"
			)  # no context: keep the rest going
	return count


def notify(row):
	"""Tell the lab in-charge; the task and its due date make the dedupe token, so a renewed date is notified afresh."""
	doc = frappe.get_doc("Asset Maintenance", row.maintenance)
	context = {
		"asset": row.asset, "asset_name": row.asset_name, "laboratory": row.laboratory, "task": row.task,
		"due_date": str(row.next_due_date), "days": row.days_left,
		"dedupe_token": f"{row.task_name}-{row.next_due_date}",
	}  # fmt: skip
	send(EVENT, doc, [f"Employee:{row.in_charge}"], context=context)
