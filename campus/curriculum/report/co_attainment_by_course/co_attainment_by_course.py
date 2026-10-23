"""M03-03 CO Attainment by Course / Faculty: the CO levels of submitted CO Attainment Runs, with the offering's
faculty and the gap to the target. Limited to the colleges the user is permitted for; runs are read with the user's
permissions."""

import frappe
from frappe import _

from campus.curriculum.attainment import CO_RESULT, CO_RUN, check_company, offering_instructors
from campus.curriculum.attainment_rules import gap, shown

FILTERS = ("academic_year", "academic_term", "program", "course")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission(CO_RUN, "read", throw=True)
	check_company(filters.company)
	return columns(), rows(filters)


def rows(filters):
	conditions = {"docstatus": 1, "company": filters.company, **{f: filters[f] for f in FILTERS if filters.get(f)}}
	if filters.instructor:
		taught = frappe.get_all("Student Group Instructor", {"parenttype": "Student Group", "instructor": filters.instructor}, pluck="parent")
		conditions["course_offering"] = ["in", taught or [""]]
	runs = {r.name: r for r in frappe.get_list(CO_RUN, filters=conditions, fields=["name", "course", "course_offering", "academic_term"], order_by="name")}
	faculty = offering_instructors({r.course_offering for r in runs.values()})
	results = frappe.get_all(
		CO_RESULT, {"parenttype": CO_RUN, "parent": ["in", list(runs) or [""]]},
		["parent", "co_code", "cia_students", "cia_percent", "ese_students", "ese_percent", "assessed", "direct_level", "has_indirect",
		"indirect_level", "final_level", "target_level", "target_met"],
		order_by="parent, idx",
	)  # fmt: skip
	results = [frappe._dict(shown(r)) for r in results]
	return [
		{**r, "run": r.parent, "course": runs[r.parent].course, "course_offering": runs[r.parent].course_offering,
		"academic_term": runs[r.parent].academic_term, "instructors": ", ".join(faculty.get(runs[r.parent].course_offering, [])),
		"gap": gap(r.final_level, r.target_level)}
		for r in results
	]  # fmt: skip


def columns():
	return [
		{"fieldname": "course", "label": _("Course"), "fieldtype": "Link", "options": "Course", "width": 180},
		{"fieldname": "course_offering", "label": _("Offering"), "fieldtype": "Link", "options": "Student Group", "width": 180},
		{"fieldname": "academic_term", "label": _("Term"), "fieldtype": "Link", "options": "Academic Term", "width": 130},
		{"fieldname": "instructors", "label": _("Faculty"), "fieldtype": "Data", "width": 160},
		{"fieldname": "co_code", "label": _("CO"), "fieldtype": "Data", "width": 60},
		{"fieldname": "cia_percent", "label": _("CIA %"), "fieldtype": "Percent", "width": 80},
		{"fieldname": "ese_percent", "label": _("ESE %"), "fieldtype": "Percent", "width": 80},
		{"fieldname": "direct_level", "label": _("Direct"), "fieldtype": "Float", "width": 80},
		{"fieldname": "indirect_level", "label": _("Indirect"), "fieldtype": "Float", "width": 80},
		{"fieldname": "final_level", "label": _("Final"), "fieldtype": "Float", "width": 80},
		{"fieldname": "target_level", "label": _("Target"), "fieldtype": "Float", "width": 80},
		{"fieldname": "gap", "label": _("Gap"), "fieldtype": "Float", "width": 80},
		{"fieldname": "run", "label": _("Run"), "fieldtype": "Link", "options": CO_RUN, "width": 120},
	]
