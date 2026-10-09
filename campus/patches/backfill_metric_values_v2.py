"""Re-run of backfill_metric_values under a new name: sites that ran the first (no-op) version of it recorded it in
Patch Log and would never run the corrected body. Idempotent: a fixed row no longer matches."""

from campus.patches.backfill_metric_values import backfill


def execute():
	backfill()
