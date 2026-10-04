"""M03-04 Elective Enrolment: seat cap, enrolment and the below-minimum flag of every elective offering.

Enrolment is the membership of the course's offering groups. Limited to the companies the user is
permitted for; the elective minimum comes from the regulation's Registration Rule.
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

from campus.campus_platform.company_scope import permitted_companies
from campus.curriculum.enrollment import count_members
from campus.curriculum.registration_rules import elective_status


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "course", "label": _("Course"), "fieldtype": "Link", "options": "Course", "width": 220},
		{"fieldname": "curriculum", "label": _("Curriculum"), "fieldtype": "Link", "options": "Curriculum", "width": 160},
		{"fieldname": "semester", "label": _("Semester"), "fieldtype": "Int", "width": 80},
		{"fieldname": "elective_group", "label": _("Elective Group"), "fieldtype": "Link", "options": "Elective Group", "width": 140},
		{"fieldname": "offerings", "label": _("Offerings"), "fieldtype": "Int", "width": 90},
		{"fieldname": "seat_cap", "label": _("Seat Cap"), "fieldtype": "Int", "width": 90},
		{"fieldname": "enrolled", "label": _("Enrolled"), "fieldtype": "Int", "width": 90},
		{"fieldname": "minimum", "label": _("Minimum"), "fieldtype": "Int", "width": 90},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 120},
		{"fieldname": "below_minimum", "label": _("Below Minimum"), "fieldtype": "Check", "width": 110},
	]


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	closed = window_closed(filters.company, filters.academic_term)
	rows = []
	for (curriculum, course), offerings in offering_groups(filters).items():
		elective = elective_row(curriculum, course)
		if not elective:
			continue
		rows.append(report_row(curriculum, course, elective, len(offerings), filters.academic_term, closed))
	return sorted(rows, key=lambda r: (r["curriculum"], r["semester"], r["course"]))


def window_closed(company, academic_term):
	closes = frappe.get_all(
		"Registration Window", {"company": company, "academic_term": academic_term}, pluck="closes_on"
	)
	return bool(closes) and all(getdate(c) < getdate(today()) for c in closes)


def offering_groups(filters):
	conditions = {
		"oc_company": filters.company, "academic_term": filters.academic_term, "oc_curriculum": ["is", "set"],
	}
	if filters.program:
		conditions["program"] = filters.program
	groups = {}
	for group in frappe.get_list("Student Group", filters=conditions, fields=["name", "oc_curriculum", "course"]):
		groups.setdefault((group.oc_curriculum, group.course), []).append(group.name)
	return groups


def elective_row(curriculum, course):
	return frappe.db.get_value(
		"Curriculum Course",
		{"parent": curriculum, "course": course, "is_elective": 1, "elective_group": ["is", "set"]},
		["semester", "elective_group"],
		as_dict=True,
	)


def report_row(curriculum, course, elective, offerings, academic_term, closed):
	regulation = frappe.db.get_value("Curriculum", curriculum, "regulation")
	minimum = frappe.db.get_value("Registration Rule", {"regulation": regulation}, "elective_min_enrolment") or 0
	enrolled = count_members(curriculum, course, academic_term)
	status = elective_status(enrolled, minimum, closed)
	return {
		"course": course, "curriculum": curriculum, "semester": elective.semester,
		"elective_group": elective.elective_group, "offerings": offerings,
		"seat_cap": frappe.db.get_value("Elective Group", elective.elective_group, "seat_cap_per_course"),
		"enrolled": enrolled, "minimum": minimum, "status": status, "below_minimum": int(status == "Below Minimum"),
	}  # fmt: skip
