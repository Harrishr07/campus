"""M05-13 Mentoring Activity (L-09): per mentor of the company, the number of mentees, counselling notes (and how
many are confidential), parent interactions and overdue parent follow-ups about their current mentees. Counts only:
no note text, outcome or student is ever shown, so confidential notes are counted without being read.
"""

import frappe
from frappe import _
from frappe.utils import today

from campus.campus_platform.company_scope import permitted_companies
from campus.student_services.mentoring import HOD_ROLE, INTERACTION, NOTE, COUNSELLOR_ROLE, PRINCIPAL_ROLE

REPORT_ROLES = (HOD_ROLE, PRINCIPAL_ROLE, COUNSELLOR_ROLE)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.only_for(REPORT_ROLES)
	check_company(filters.company)
	return columns(), rows(filters)


def check_company(company):
	if not company:
		frappe.throw(_("Choose a company."))
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and company not in permitted:
		frappe.throw(_("You are not permitted to see {0}.").format(company), frappe.PermissionError)


def columns():
	return [
		{"fieldname": "mentor", "label": _("Mentor"), "fieldtype": "Link", "options": "Employee", "width": 140},
		{"fieldname": "mentor_name", "label": _("Mentor Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "mentees", "label": _("Mentees"), "fieldtype": "Int", "width": 100},
		{"fieldname": "note_count", "label": _("Counselling Notes"), "fieldtype": "Int", "width": 140},
		{"fieldname": "confidential_count", "label": _("Confidential"), "fieldtype": "Int", "width": 110},
		{"fieldname": "interaction_count", "label": _("Parent Interactions"), "fieldtype": "Int", "width": 150},
		{"fieldname": "overdue_follow_ups", "label": _("Overdue Follow-ups"), "fieldtype": "Int", "width": 150},
	]


def rows(filters):
	mentees = counts_by_mentor("select oc_mentor, count(*) from `tabStudent` where oc_company = %(company)s and oc_mentor is not null and oc_mentor != '' group by oc_mentor", filters)
	notes = counts_by_mentor(per_mentor_sql(NOTE, "note_date", "count(*)"), filters)
	confidential = counts_by_mentor(per_mentor_sql(NOTE, "note_date", "sum(ifnull(r.is_confidential, 0))"), filters)
	interactions = counts_by_mentor(per_mentor_sql(INTERACTION, "interaction_date", "count(*)"), filters)
	overdue_sql = "sum(ifnull(r.follow_up_done, 0) = 0 and r.follow_up_due < %(today)s)"
	overdue = counts_by_mentor(per_mentor_sql(INTERACTION, "interaction_date", overdue_sql), filters)
	names = dict(frappe.get_all("Employee", {"name": ["in", list(mentees) or [""]]}, ["name", "employee_name"], as_list=True))
	return [
		{
			"mentor": mentor, "mentor_name": names.get(mentor), "mentees": mentees[mentor], "note_count": notes.get(mentor, 0),
			"confidential_count": confidential.get(mentor, 0), "interaction_count": interactions.get(mentor, 0),
			"overdue_follow_ups": overdue.get(mentor, 0),
		}
		for mentor in sorted(mentees, key=lambda m: (names.get(m) or "", m))
	]  # fmt: skip


def per_mentor_sql(doctype, date_field, aggregate):
	"""`aggregate` over the doctype's rows of the company's students, grouped by the student's current mentor."""
	return (
		f"select s.oc_mentor, {aggregate} from `tab{doctype}` r join `tabStudent` s on s.name = r.student"
		" where r.company = %(company)s and s.oc_mentor is not null and s.oc_mentor != ''"
		f" and (%(from_date)s is null or r.{date_field} >= %(from_date)s)"
		f" and (%(to_date)s is null or r.{date_field} <= %(to_date)s)"
		" group by s.oc_mentor"
	)


def counts_by_mentor(sql, filters):
	values = {"company": filters.company, "from_date": filters.from_date or None, "to_date": filters.to_date or None, "today": today()}
	return {mentor: int(count or 0) for mentor, count in frappe.db.sql(sql, values)}
