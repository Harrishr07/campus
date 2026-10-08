"""M06-08 CIA Marks Audit Trail: every change to CIA marks (question marks, absent flags, consolidated CIA)
from the Mark Sheet Entry version history, the entry-deadline moves of the CIA Schedule, and the CIA Unlock
Requests raised for the offering with the decisions on them from their approval trail.

Limited to the companies the user is permitted for and to the Mark Sheet Entries the user may read."""

import json

import frappe
from frappe import _
from frappe.utils import add_days, getdate

from campus.campus_platform.company_scope import permitted_companies
from campus.examinations import cia

SHEET = "Mark Sheet Entry"
CIA_ROW_FIELDS = {"cia_marks": ("marks", "absent"), "marks": ("cia", "cia_attendance")}
DECISIONS = {"Approve": "Unlock approved", "Reject": "Unlock rejected", "Return": "Unlock returned"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "timestamp", "label": _("When"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "user", "label": _("User"), "fieldtype": "Link", "options": "User", "width": 180},
		{"fieldname": "event", "label": _("Event"), "fieldtype": "Data", "width": 130},
		{"fieldname": "document_type", "label": _("Document Type"), "fieldtype": "Link", "options": "DocType", "hidden": 1},
		{"fieldname": "document", "label": _("Document"), "fieldtype": "Dynamic Link", "options": "document_type", "width": 120},
		{"fieldname": "course_offering", "label": _("Course Offering"), "fieldtype": "Link", "options": "Student Group", "width": 180},
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 130},
		{"fieldname": "detail", "label": _("Detail"), "fieldtype": "Data", "width": 200},
		{"fieldname": "old_value", "label": _("Old"), "fieldtype": "Data", "width": 80},
		{"fieldname": "new_value", "label": _("New"), "fieldtype": "Data", "width": 80},
	]  # fmt: skip


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	conditions = {"company": filters.company}
	if filters.course_offering:
		conditions["course_offering"] = filters.course_offering
	rows = sheet_rows(filters, conditions) + deadline_rows(filters, conditions) + unlock_rows(filters, conditions)
	return sorted(rows, key=lambda row: (row["timestamp"], row["event"]))


def sheet_rows(filters, conditions):
	sheets = {s.name: s.course_offering for s in frappe.get_list(SHEET, filters=conditions, fields=["name", "course_offering"])}
	rows = []
	for version in versions(SHEET, list(sheets), filters):
		labels = row_labels(version.docname)
		changes = json.loads(version.data)
		base = {"timestamp": version.creation, "user": version.owner, "document_type": SHEET,
			"document": version.docname, "course_offering": sheets[version.docname]}  # fmt: skip
		rows += [{**base, **change} for change in cia_changes(changes, labels)]
	return rows


def cia_changes(changes, labels):
	"""Rows of the CIA fields a Version changed; added question rows are summarised in one line."""
	out = []
	for table, _idx, row_name, fields in changes.get("row_changed", []):
		student, detail = labels.get(row_name, (None, ""))
		for field, old, new in fields:
			if field in CIA_ROW_FIELDS.get(table, ()):
				out.append({"event": _("CIA edit"), "student": student, "detail": f"{detail} {field}".strip(),
					"old_value": str(old), "new_value": str(new)})  # fmt: skip
	added = [row for table, row in changes.get("added", []) if table == "cia_marks"]
	if added:
		out.append({"event": _("Questions added"), "detail": _("{0} CIA question rows").format(len(added))})
	return out


def row_labels(sheet):
	"""{child row name: (student, "component question")} of a sheet's current rows."""
	labels = {}
	for row in frappe.get_all("Mark Sheet CIA Mark", {"parent": sheet, "parenttype": SHEET}, ["name", "student", "component", "question"]):
		labels[row.name] = (row.student, f"{row.component} {row.question}")
	for row in frappe.get_all("Mark Sheet Entry Row", {"parent": sheet, "parenttype": SHEET}, ["name", "student"]):
		labels[row.name] = (row.student, "")
	return labels


def deadline_rows(filters, conditions):
	"""Moves of a CIA Schedule's entry deadline (only possible before it has passed)."""
	schedules = {s.name: s.course_offering for s in frappe.get_list(cia.SCHEDULE, filters=conditions, fields=["name", "course_offering"])}
	rows = []
	for version in versions(cia.SCHEDULE, list(schedules), filters):
		for field, old, new in json.loads(version.data).get("changed", []):
			if field == "entry_deadline":
				rows.append({"document_type": cia.SCHEDULE, "document": version.docname, "timestamp": version.creation,
					"course_offering": schedules[version.docname], "user": version.owner, "event": _("Deadline changed"),
					"detail": "entry_deadline", "old_value": str(old), "new_value": str(new)})  # fmt: skip
	return rows


def unlock_rows(filters, conditions):
	"""Each CIA Unlock Request as raised, and every decision on it from its approval trail."""
	requests = {
		r.name: r
		for r in frappe.get_list(
			cia.UNLOCK, filters=conditions, fields=["name", "course_offering", "owner", "creation", "reason", "unlock_until"]
		)
	}
	rows = [
		{"document_type": cia.UNLOCK, "document": r.name, "course_offering": r.course_offering, "timestamp": r.creation,
		"user": r.owner, "event": _("Unlock requested"), "detail": r.reason, "new_value": str(r.unlock_until)}
		for r in requests.values()
	]  # fmt: skip
	for action in approval_actions(list(requests)):
		request = requests[action.reference_name]
		rows.append({"document_type": cia.UNLOCK, "document": request.name, "course_offering": request.course_offering,
			"timestamp": action.timestamp, "user": action.approver, "event": _(DECISIONS[action.action]),
			"detail": action.comment, "new_value": str(request.unlock_until)})  # fmt: skip
	return [row for row in rows if in_range(row["timestamp"], filters)]


def approval_actions(names):
	if not names:
		return []
	request, action = frappe.qb.DocType("Approval Request"), frappe.qb.DocType("Approval Action")
	return (
		frappe.qb.from_(action)
		.join(request)
		.on(action.parent == request.name)
		.select(request.reference_name, action.action, action.approver, action.comment, action.timestamp)
		.where(request.reference_doctype == cia.UNLOCK)
		.where(request.reference_name.isin(names))
		.where(action.action.isin(list(DECISIONS)))
		.orderby(action.timestamp)
		.run(as_dict=True)
	)


def versions(doctype, names, filters):
	if not names:
		return []
	conditions = [["ref_doctype", "=", doctype], ["docname", "in", names]]
	if filters.from_date:
		conditions.append(["creation", ">=", getdate(filters.from_date)])
	if filters.to_date:
		conditions.append(["creation", "<", add_days(getdate(filters.to_date), 1)])
	return frappe.get_all("Version", conditions, ["docname", "owner", "creation", "data"], order_by="creation")


def in_range(timestamp, filters):
	day = getdate(timestamp)
	return (not filters.from_date or day >= getdate(filters.from_date)) and (
		not filters.to_date or day <= getdate(filters.to_date)
	)
