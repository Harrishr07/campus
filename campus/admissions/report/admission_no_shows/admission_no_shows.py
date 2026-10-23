"""M04-10 Admission No-Shows: admitted students who have not joined by their reporting deadline plus the grace days.

Each row shows the draft cancellation the daily referral made (or an officer did); nothing is cancelled until an
officer submits it. Limited to the companies the user is permitted for.
"""

import frappe
from frappe import _

from campus.admissions.reporting import CANCELLATION, no_shows
from campus.campus_platform.company_scope import permitted_companies


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 140},
		{"fieldname": "student_name", "label": _("Student Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "applicant", "label": _("Student Applicant"), "fieldtype": "Link", "options": "Student Applicant", "width": 140},
		{"fieldname": "program", "label": _("Program"), "fieldtype": "Link", "options": "Program", "width": 180},
		{"fieldname": "reporting_deadline", "label": _("Reporting Deadline"), "fieldtype": "Date", "width": 120},
		{"fieldname": "referral_date", "label": _("No-Show From"), "fieldtype": "Date", "width": 120},
		{"fieldname": "cancellation", "label": _("Draft Cancellation"), "fieldtype": "Link", "options": CANCELLATION, "width": 160},
	]


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if not filters.company or (permitted is not None and filters.company not in permitted):
		return []
	rows = no_shows(filters.as_of, filters.company)
	drafts = dict(
		frappe.get_all(
			CANCELLATION, {"student": ("in", [r.student for r in rows] or [""]), "docstatus": 0}, ["student", "name"], as_list=True
		)
	)  # a submitted one has moved the student to Cancelled, off this list
	for row in rows:
		row.cancellation = drafts.get(row.student)
	return rows
