"""M01-02 Metric Values made before computed_value and status existed held the engine's value in `value`: keep it as the
computed value and mark them Computed. The new Float column is NOT NULL (0), so a legacy computed row is one with
computed_at set, computed_value 0, a non-zero value and no approved override. Re-runnable: a fixed row no longer matches."""

import frappe


def execute():
	backfill()


def backfill():
	frappe.db.sql(
		"update `tabMetric Value` set computed_value = value, status = 'Computed' "
		"where status = 'Draft' and computed_at is not null and computed_value = 0 and value <> 0 and override_approved = 0"
	)
