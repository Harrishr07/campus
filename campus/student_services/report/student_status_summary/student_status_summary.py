"""M05-09 Student Status Summary: the company's students by programme and batch, counted per lifecycle status.

The programme is that of the student's latest submitted Program Enrollment (a cancelled one when none is
submitted, so cancelled admissions are counted). Limited to the companies the user is permitted for; the Student
list itself is read with the user's permissions.
"""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies
from campus.student_services.lifecycle_rules import STATUSES


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{
			"fieldname": "program",
			"label": _("Program"),
			"fieldtype": "Link",
			"options": "Program",
			"width": 200,
		},
		{
			"fieldname": "batch",
			"label": _("Batch"),
			"fieldtype": "Link",
			"options": "Academic Year",
			"width": 120,
		},
		*(
			{"fieldname": frappe.scrub(status), "label": _(status), "fieldtype": "Int", "width": 110}
			for status in STATUSES
		),
		{"fieldname": "total", "label": _("Total"), "fieldtype": "Int", "width": 90},
	]


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if not filters.company or (permitted is not None and filters.company not in permitted):
		return []
	conditions = {"oc_company": filters.company}
	if filters.batch:
		conditions["oc_batch"] = filters.batch
	students = frappe.get_list("Student", conditions, ["name", "oc_batch", "oc_academic_status"], limit=0)
	programs = student_programs([s.name for s in students])
	rows = {}
	for student in students:
		program = programs.get(student.name)
		if filters.program and program != filters.program:
			continue
		row = rows.setdefault((program or "", student.oc_batch or ""), new_row(program, student.oc_batch))
		key = frappe.scrub(student.oc_academic_status or "")
		if key in row:
			row[key] += 1
		row["total"] += 1
	return [rows[key] for key in sorted(rows)]


def new_row(program, batch):
	return {
		"program": program,
		"batch": batch,
		**{frappe.scrub(status): 0 for status in STATUSES},
		"total": 0,
	}


def student_programs(students):
	"""{student: programme of the latest submitted enrollment, else of the latest cancelled one}."""
	if not students:
		return {}
	rows = frappe.get_all(
		"Program Enrollment",
		{"student": ["in", students], "docstatus": ["in", [1, 2]]},
		["student", "program", "docstatus"],
		order_by="enrollment_date asc, creation asc",
		limit=0,
	)
	found = {}
	for row in sorted(rows, key=lambda r: r.docstatus == 1):  # stable: submitted ones last, so they win
		found[row.student] = row.program
	return found
