"""M04-01 Live Seat Matrix: sanctioned, allotted, filled and vacant seats per quota and category, counted now.

Filled and allotted are counted live from submitted Program Enrollments and applicants, not read from the
stored row counts, so the report is right even before a recount. Limited to the companies the user is
permitted for.
"""

import frappe
from frappe import _

from campus.admissions import seat_matrix
from campus.campus_platform.company_scope import permitted_companies


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "program", "label": _("Program"), "fieldtype": "Link", "options": "Program", "width": 200},
		{"fieldname": "academic_year", "label": _("Academic Year"), "fieldtype": "Link", "options": "Academic Year", "width": 120},
		{"fieldname": "quota", "label": _("Quota"), "fieldtype": "Link", "options": "Admission Quota", "width": 120},
		{"fieldname": "category", "label": _("Category"), "fieldtype": "Link", "options": "Student Category", "width": 110},
		{"fieldname": "sanctioned", "label": _("Sanctioned"), "fieldtype": "Int", "width": 100},
		{"fieldname": "allotted", "label": _("Allotted"), "fieldtype": "Int", "width": 90},
		{"fieldname": "filled", "label": _("Filled"), "fieldtype": "Int", "width": 90},
		{"fieldname": "vacant", "label": _("Vacant"), "fieldtype": "Int", "width": 90},
		{"fieldname": "supernumerary", "label": _("Supernumerary"), "fieldtype": "Check", "width": 110},
	]


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	conditions = {"company": filters.company}
	for field in ("program", "academic_year"):
		if filters.get(field):
			conditions[field] = filters[field]
	rows = []
	for matrix in frappe.get_list("Seat Matrix", filters=conditions, fields=["name", "company", "program", "academic_year"], order_by="program, academic_year"):
		rows += matrix_rows(matrix)
	return rows


def matrix_rows(matrix):
	filled = seat_matrix.count_filled(matrix.company, matrix.program, matrix.academic_year)
	allotted = seat_matrix.count_allotted(matrix.program, matrix.academic_year)
	seats = frappe.get_all(
		"Seat Matrix Row", {"parent": matrix.name}, ["quota", "category", "sanctioned"], order_by="idx", limit=0
	)
	rows = []
	for seat in seats:
		pair = (seat.quota, seat.category)
		rows.append(
			{
				"program": matrix.program, "academic_year": matrix.academic_year, "quota": seat.quota, "category": seat.category,
				"sanctioned": seat.sanctioned, "allotted": allotted.get(pair, 0), "filled": filled.get(pair, 0),
				"vacant": seat.sanctioned - filled.get(pair, 0),
				"supernumerary": int(not seat_matrix.counts_in_matrix(seat.quota)),
			}
		)  # fmt: skip
	return rows
