"""M04-09 The Admission Officer no longer reads Sales Invoice and Payment Entry (the kit once gave it): Confirm Joining
and Admission Cancellation raise them with elevated rights. Runs once, so a read the college grants again stays."""

import frappe

OFFICER_ROLE = "Admission Officer"


def execute():
	for doctype in ("Sales Invoice", "Payment Entry"):
		frappe.db.delete("Custom DocPerm", {"parent": doctype, "role": OFFICER_ROLE, "permlevel": 0})
		frappe.clear_cache(doctype=doctype)
