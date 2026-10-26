"""M04-08 Programs without Seat Matrix (rollout check): the company's programs with no Seat Matrix for the year.

In strict mode a joining into such a program is refused unless an override is logged, so the admission office
sets these up first. Applicants counts the program's Approved and Admitted applicants of the year (still to
join). Limited to the companies the user is permitted for; programs are read with the user's permissions.
"""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies

WAITING = ("Approved", "Admitted")


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
			"width": 220,
		},
		{
			"fieldname": "academic_year",
			"label": _("Academic Year"),
			"fieldtype": "Link",
			"options": "Academic Year",
			"width": 130,
		},
		{"fieldname": "applicants", "label": _("Applicants"), "fieldtype": "Int", "width": 110},
	]


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if (
		not filters.company
		or not filters.academic_year
		or (permitted is not None and filters.company not in permitted)
	):
		return []
	programs = frappe.get_list(
		"Program", {"oc_company": filters.company}, pluck="name", order_by="name", limit=0
	)
	with_matrix = set(
		frappe.get_all(
			"Seat Matrix",
			{"company": filters.company, "academic_year": filters.academic_year},
			pluck="program",
		)
	)
	missing = [program for program in programs if program not in with_matrix]
	waiting = applicant_counts(missing, filters.academic_year)
	return [
		{"program": p, "academic_year": filters.academic_year, "applicants": waiting.get(p, 0)}
		for p in missing
	]


def applicant_counts(programs, academic_year):
	if not programs:
		return {}
	rows = frappe.get_all(
		"Student Applicant",
		filters={
			"program": ["in", programs],
			"academic_year": academic_year,
			"application_status": ["in", WAITING],
		},
		fields=["program", {"COUNT": "name", "as": "n"}],
		group_by="program",
	)
	return {row.program: row.n for row in rows}
