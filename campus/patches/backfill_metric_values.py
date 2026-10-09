"""M01-02 Metric Values made before computed_value and status existed held the engine's value in `value`: keep it as the
computed value and mark them Computed. Re-runnable: only rows without a computed value are touched."""

import frappe


def execute():
	frappe.db.sql(
		"update `tabMetric Value` set computed_value = value, status = 'Computed' "
		"where computed_value is null and value is not null and (manual_value is null)"
	)
	frappe.db.sql("update `tabMetric Value` set status = 'Draft' where status is null or status = ''")
