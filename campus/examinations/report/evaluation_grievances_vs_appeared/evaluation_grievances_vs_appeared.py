"""M06-06 / AQAR 2.5.2 Evaluation Grievances vs Appeared: per released exam session of the company in the academic
year, the students who appeared (sat at least one course on their published result), the students with a grievance
about evaluation (a submitted Revaluation or Review application; a photocopy alone is not one) and the percentage.
The total row counts distinct students over the year, as the evaluation_grievances data point does.

Limited to the companies the user is permitted for and to the exam sessions and applications the user may read."""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies
from campus.examinations.coe_reports import released_sessions
from campus.examinations.revaluation import GRIEVANCE_TYPES, appeared_students
from campus.examinations.revaluation_rules import grievance_pct


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "exam_session", "label": _("Exam Session"), "fieldtype": "Data", "width": 140},  # Data: the Total row
		{"fieldname": "academic_term", "label": _("Academic Term"), "fieldtype": "Link", "options": "Academic Term", "width": 160},
		{"fieldname": "appeared", "label": _("Students Appeared"), "fieldtype": "Int", "width": 130},
		{"fieldname": "grievances", "label": _("Students with Grievances"), "fieldtype": "Int", "width": 160},
		{"fieldname": "grievance_pct", "label": _("Grievances %"), "fieldtype": "Percent", "width": 110},
	]  # fmt: skip


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	sessions = released_sessions(filters.company, filters.academic_year, lister=frappe.get_list, fields=("name", "academic_term"))
	applications = frappe.get_list(
		"Revaluation Application",
		filters={"exam_session": ["in", [s.name for s in sessions] or [""]], "docstatus": 1, "application_type": ["in", GRIEVANCE_TYPES]},
		fields=["student", "exam_session"],
	)  # fmt: skip
	out, all_appeared, all_grieved = [], set(), set()
	for session in sessions:
		appeared = appeared_students(session.name)
		grieved = {a.student for a in applications if a.exam_session == session.name}
		all_appeared |= appeared
		all_grieved |= grieved
		out.append(
			{"exam_session": session.name, "academic_term": session.academic_term, "appeared": len(appeared),
			"grievances": len(grieved), "grievance_pct": grievance_pct(len(grieved), len(appeared))}
		)  # fmt: skip
	if out:
		out.append(
			{"exam_session": _("Total (distinct students)"), "appeared": len(all_appeared), "grievances": len(all_grieved),
			"grievance_pct": grievance_pct(len(all_grieved), len(all_appeared))}
		)  # fmt: skip
	return out
