"""M05-06 Grievance SLA: each grievance's level, deadline and escalations, and whether it is within SLA.

Limited to the grievances the user may read (confidential ones need the committee role) and to a company.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime, time_diff_in_hours

from campus.campus_platform.approval_rules import ESCALATE, PENDING
from campus.campus_platform.company_scope import permitted_companies

FIELDS = ["name", "student", "student_name", "category", "department", "status", "raised_on", "resolved_on", "docstatus"]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "name", "label": _("Grievance"), "fieldtype": "Link", "options": "Student Grievance", "width": 140},
		{"fieldname": "student_name", "label": _("Student"), "fieldtype": "Data", "width": 160},
		{"fieldname": "category", "label": _("Category"), "fieldtype": "Link", "options": "Grievance Type", "width": 140},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 90},
		{"fieldname": "raised_on", "label": _("Raised On"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "current_level", "label": _("Level"), "fieldtype": "Int", "width": 70},
		{"fieldname": "due_at", "label": _("Level Due At"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "escalations", "label": _("Escalations"), "fieldtype": "Int", "width": 100},
		{"fieldname": "hours_open", "label": _("Hours Open"), "fieldtype": "Float", "width": 100},
		{"fieldname": "sla", "label": _("SLA"), "fieldtype": "Data", "width": 110},
	]  # fmt: skip


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	query = {"company": filters.company}
	if filters.get("status"):
		query["status"] = filters.status
	grievances = frappe.get_list("Student Grievance", query, FIELDS, order_by="raised_on desc", limit=0)
	requests = requests_of([g.name for g in grievances])
	now = now_datetime()
	return [row(g, requests.get(g.name), now) for g in grievances]


def requests_of(names):
	"""{grievance: {current_level, due_at, status, escalations}} from the grievances' approval requests."""
	found = {}
	for request in frappe.get_all(
		"Approval Request",
		{"reference_doctype": "Student Grievance", "reference_name": ["in", names or [""]]},
		["name", "reference_name", "current_level", "due_at", "status"],
		order_by="creation asc", limit=0,
	):  # fmt: skip
		request["escalations"] = frappe.db.count("Approval Action", {"parent": request.name, "action": ESCALATE})
		found[request.reference_name] = request
	return found


def row(grievance, request, now):
	request = request or frappe._dict()
	end = grievance.resolved_on or now
	return {
		"name": grievance.name, "student_name": grievance.student_name, "category": grievance.category,
		"status": _(grievance.status), "raised_on": grievance.raised_on, "current_level": request.get("current_level"),
		"due_at": request.get("due_at") if request.get("status") == PENDING else None,
		"escalations": request.get("escalations") or 0,
		"hours_open": round(time_diff_in_hours(end, grievance.raised_on), 1),
		"sla": sla_status(grievance, request, now),
	}  # fmt: skip


def sla_status(grievance, request, now):
	if grievance.docstatus != 0:
		return _("Closed")
	if request.get("due_at") and get_datetime(request.due_at) < now:
		return _("Overdue")
	return _("Within SLA")
