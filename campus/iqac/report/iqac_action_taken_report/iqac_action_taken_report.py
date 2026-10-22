"""M01-04 IQAC Action Taken Report: the Meeting Action Items of the period's meetings with the action taken, and which are overdue.
Items of confidential committees are listed only for users who may read them."""

import frappe
from frappe import _
from frappe.utils import getdate, today

from campus.academic_governance import api as governance
from campus.academic_governance.actions import OPEN_STATUSES


def execute(filters=None):
	filters = frappe._dict(filters or {})
	items = governance.action_items(filters.company, filters.from_date, filters.to_date, filters.body_type)
	return columns(), [row(item) for item in items]


def columns():
	return [
		{"fieldname": "meeting_date", "label": _("Meeting Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "body_meeting", "label": _("Meeting"), "fieldtype": "Link", "options": "Body Meeting", "width": 150},
		{"fieldname": "body", "label": _("Committee"), "fieldtype": "Link", "options": "Body", "width": 200},
		{"fieldname": "resolution_no", "label": _("Resolution No"), "fieldtype": "Data", "width": 120},
		{"fieldname": "action_item", "label": _("Action Item"), "fieldtype": "Link", "options": "Meeting Action Item", "width": 130},
		{"fieldname": "action", "label": _("Action"), "fieldtype": "Data", "width": 260},
		{"fieldname": "responsible", "label": _("Responsible"), "fieldtype": "Link", "options": "Employee", "width": 130},
		{"fieldname": "due_date", "label": _("Due"), "fieldtype": "Date", "width": 100},
		{"fieldname": "state", "label": _("State"), "fieldtype": "Data", "width": 110},
		{"fieldname": "action_taken", "label": _("Action Taken"), "fieldtype": "Data", "width": 280},
	]  # fmt: skip


def state(item):
	if item.status in OPEN_STATUSES and item.due_date and getdate(item.due_date) < getdate(today()):
		return "Overdue"
	return item.status


def row(item):
	return {**item, "action_item": item.name, "state": state(item)}
