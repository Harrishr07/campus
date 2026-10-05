"""M04-01 Admissions by Quota and Category: students admitted (submitted Program Enrollments), AQAR 2.1.1 / 2.1.2 data.

One row per value of each grouping: Total, Quota, Category, Gender and State. AQAR 2.1.1 is the Total (and its
year-wise split via the year filter); AQAR 2.1.2 is read from the Category rows (seats sanctioned for the
category in the Seat Matrix against students admitted). Limited to the companies the user is permitted for.
"""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies

GROUPS = (("Quota", "oc_admission_quota"), ("Category", "student_category"), ("Gender", "gender"), ("State", "state"))


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "grouping", "label": _("Grouping"), "fieldtype": "Data", "width": 110},
		{"fieldname": "value", "label": _("Value"), "fieldtype": "Data", "width": 200},
		{"fieldname": "admitted", "label": _("Students Admitted"), "fieldtype": "Int", "width": 130},
		{"fieldname": "sanctioned", "label": _("Seats Sanctioned (Seat Matrix)"), "fieldtype": "Int", "width": 190},
	]


def admitted_students(filters):
	enrollment, student = frappe.qb.DocType("Program Enrollment"), frappe.qb.DocType("Student")
	query = (
		frappe.qb.from_(enrollment)
		.join(student).on(student.name == enrollment.student)
		.select(enrollment.oc_admission_quota, enrollment.student_category, student.gender, student.state)
		.where((enrollment.docstatus == 1) & (enrollment.oc_company == filters.company))
	)  # fmt: skip
	for field in ("program", "academic_year"):
		if filters.get(field):
			query = query.where(enrollment[field] == filters[field])
	return query.run(as_dict=True)


def sanctioned_by_category(filters):
	matrix = {"company": filters.company}
	for field in ("program", "academic_year"):
		if filters.get(field):
			matrix[field] = filters[field]
	names = frappe.get_all("Seat Matrix", matrix, pluck="name", limit=0)
	rows = frappe.get_all("Seat Matrix Row", {"parent": ("in", names or [""])}, ["category", "sanctioned"], limit=0)
	totals = {}
	for row in rows:
		totals[row.category] = totals.get(row.category, 0) + (row.sanctioned or 0)
	return totals


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if not filters.company or (permitted is not None and filters.company not in permitted):
		return []
	students = admitted_students(filters)
	sanctioned = sanctioned_by_category(filters)
	rows = [{"grouping": _("Total"), "value": "", "admitted": len(students), "sanctioned": sum(sanctioned.values())}]
	for label, field in GROUPS:
		counts = {}
		for student in students:
			key = student.get(field) or _("Not set")
			counts[key] = counts.get(key, 0) + 1
		for value in sorted(counts):
			rows.append(
				{"grouping": _(label), "value": value, "admitted": counts[value],
				 "sanctioned": sanctioned.get(value) if label == "Category" else None}
			)  # fmt: skip
	return rows
