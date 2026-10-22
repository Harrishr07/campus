"""M04-08 Turn strict seat matrix on for existing sites, and give the Seat Override Logs made before it (all of
them overrides of a full row) their reason. DML only."""

import frappe

from campus.admissions.seat_matrix import ROW_FULL


def execute():
	frappe.db.set_single_value("Admission Settings", "strict_seat_matrix", 1)
	frappe.db.sql("update `tabSeat Override Log` set reason = %s where ifnull(reason, '') = ''", ROW_FULL)
