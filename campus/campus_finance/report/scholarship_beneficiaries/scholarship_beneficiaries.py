"""M05-05 Scholarship Beneficiaries: sanctioned scholarships of a company, split by AQAR clause.

5.1.1 is the government schemes and 5.1.2 the institutional ones. The summary counts distinct students per clause.
Limited to the companies the user is permitted for.
"""

import frappe
from frappe import _

from campus.campus_finance.scholarships import AQAR_CLAUSE, GOVERNMENT, INSTITUTIONAL, scholarship_beneficiaries
from campus.campus_platform.company_scope import permitted_companies


def execute(filters=None):
	filters = frappe._dict(filters or {})
	rows = data(filters)
	return columns(), rows, None, None, summary(rows)


def columns():
	return [
		{"fieldname": "aqar_clause", "label": _("AQAR"), "fieldtype": "Data", "width": 70},
		{"fieldname": "scheme", "label": _("Scheme"), "fieldtype": "Link", "options": "Scholarship Scheme", "width": 170},
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 130},
		{"fieldname": "student_name", "label": _("Student Name"), "fieldtype": "Data", "width": 170},
		{"fieldname": "academic_year", "label": _("Academic Year"), "fieldtype": "Link", "options": "Academic Year", "width": 110},
		{"fieldname": "sanctioned_amount", "label": _("Sanctioned"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "disbursed_amount", "label": _("Disbursed"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "name", "label": _("Application"), "fieldtype": "Link", "options": "Scholarship Application", "width": 140},
	]  # fmt: skip


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	return scholarship_beneficiaries(filters.company, filters.get("academic_year"), filters.get("scheme_type"))


def summary(rows):
	students = {clause: {r.student for r in rows if r.aqar_clause == clause} for clause in AQAR_CLAUSE.values()}
	labels = {AQAR_CLAUSE[GOVERNMENT]: _("5.1.1 Government (students)"), AQAR_CLAUSE[INSTITUTIONAL]: _("5.1.2 Institutional (students)")}
	return [{"label": labels[clause], "value": len(found), "indicator": "Blue", "datatype": "Int"} for clause, found in students.items()]
