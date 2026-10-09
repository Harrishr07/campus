"""M01-04 IQAC Calendar: the meetings of Bodies of Body Type IQAC and the regulator submissions falling due in the period."""

import frappe
from frappe import _

from campus.academic_governance import api as governance

IQAC_BODY_TYPE = "IQAC"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	rows = meeting_rows(filters) + submission_rows(filters)
	return columns(), sorted(rows, key=lambda r: str(r["date"]))


def columns():
	return [
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "kind", "label": _("Kind"), "fieldtype": "Data", "width": 160},
		{"fieldname": "title", "label": _("Title"), "fieldtype": "Data", "width": 300},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "reference_doctype", "label": _("Document Type"), "fieldtype": "Data", "hidden": 1},
		{"fieldname": "reference", "label": _("Reference"), "fieldtype": "Dynamic Link", "options": "reference_doctype", "width": 170},
	]  # fmt: skip


def meeting_rows(filters):
	return [
		{"date": m.meeting_date, "kind": _("IQAC Meeting"), "title": m.body, "status": m.status, "reference_doctype": "Body Meeting", "reference": m.name}
		for m in governance.body_meetings(filters.company, filters.from_date, filters.to_date, IQAC_BODY_TYPE)
	]  # fmt: skip


def submission_rows(filters):
	submissions = frappe.get_list(
		"Regulator Submission",
		{"company": filters.company, "status": ["!=", "Waived"], "due_date": ["between", [filters.from_date, filters.to_date]]},
		["name", "submission_type", "due_date", "status"],
	)
	return [
		{"date": s.due_date, "kind": _("Regulator Submission Due"), "title": s.submission_type, "status": s.status, "reference_doctype": "Regulator Submission", "reference": s.name}
		for s in submissions
	]  # fmt: skip
