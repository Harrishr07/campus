"""M04-05 Follow-up reminders: a daily job gives the officer assigned to an open enquiry a ToDo for each
Enquiry Follow-up Rule whose day has been reached. One ToDo per (enquiry, rule), so reruns add nothing."""

import frappe
from frappe.utils import add_days, nowdate

OPEN_STATUSES = ("Lead", "Open", "Replied", "Interested")


def create_due_todos():
	"""Scheduled daily; returns the ToDo names created."""
	created = []
	for rule in frappe.get_all("Enquiry Follow-up Rule", {"enabled": 1}, ["name", "company", "days_after", "message"], limit=0):
		for lead in due_leads(rule):
			created += remind(rule, lead)
	return created


def due_leads(rule):
	return frappe.get_all(
		"Lead",
		{
			"company": rule.company, "status": ("in", OPEN_STATUSES), "oc_program_interest": ("is", "set"),
			"creation": ("<=", add_days(nowdate(), 1 - rule.days_after)),
		},
		["name", "lead_name", "oc_program_interest"], limit=0,
	)  # fmt: skip


def remind(rule, lead):
	if frappe.db.exists("ToDo", {"reference_type": "Lead", "reference_name": lead.name, "oc_followup_rule": rule.name}):
		return []
	assignees = frappe.get_all(
		"ToDo", {"reference_type": "Lead", "reference_name": lead.name, "status": "Open", "oc_followup_rule": ("is", "not set")},
		pluck="allocated_to", order_by="creation", limit=0,
	)  # fmt: skip
	if not assignees:
		return []
	todo = frappe.get_doc(
		{
			"doctype": "ToDo", "allocated_to": assignees[0], "reference_type": "Lead", "reference_name": lead.name,
			"description": frappe.render_template(rule.message, {"doc": lead}), "oc_followup_rule": rule.name,
			"date": nowdate(), "assigned_by": "Administrator",
		}
	).insert(ignore_permissions=True)  # fmt: skip
	return [todo.name]
