"""M04-05 The enquiry acknowledgement is not urgent: it waits out quiet hours. Re-runnable."""

import frappe


def execute():
	if frappe.db.exists("Message Template", "admission.enquiry_ack"):
		frappe.db.set_value("Message Template", "admission.enquiry_ack", "urgent", 0)
