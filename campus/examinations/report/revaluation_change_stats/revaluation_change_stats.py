"""M06-06 Revaluation Change Stats: per exam session and course, the submitted Revaluation Outcomes (revaluations
and reviews), how many raised, lowered or kept the ESE, how many changed the grade, and the average ESE change.

Limited to the companies the user is permitted for and to the outcomes the user may read."""

import frappe
from frappe import _
from frappe.utils import flt

from campus.campus_platform.company_scope import permitted_companies
from campus.examinations.revaluation_rules import DECREASED, INCREASED, UNCHANGED, change_direction


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "exam_session", "label": _("Exam Session"), "fieldtype": "Link", "options": "Exam Session", "width": 120},
		{"fieldname": "course", "label": _("Course"), "fieldtype": "Link", "options": "Course", "width": 140},
		{"fieldname": "outcomes", "label": _("Outcomes"), "fieldtype": "Int", "width": 90},
		{"fieldname": "increased", "label": _("ESE Raised"), "fieldtype": "Int", "width": 90},
		{"fieldname": "decreased", "label": _("ESE Lowered"), "fieldtype": "Int", "width": 90},
		{"fieldname": "unchanged", "label": _("Unchanged"), "fieldtype": "Int", "width": 90},
		{"fieldname": "grade_changed", "label": _("Grade Changed"), "fieldtype": "Int", "width": 110},
		{"fieldname": "average_change", "label": _("Average ESE Change"), "fieldtype": "Float", "width": 130},
	]  # fmt: skip


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	conditions = {"company": filters.company, "docstatus": 1}
	if filters.exam_session:
		conditions["exam_session"] = filters.exam_session
	outcomes = frappe.get_list(
		"Revaluation Outcome", filters=conditions,
		fields=["exam_session", "course", "original_ese", "new_ese", "ese_change", "original_grade", "revised_grade"],
		order_by="exam_session, course",
	)  # fmt: skip
	rows = {}
	for o in outcomes:
		row = rows.setdefault(
			(o.exam_session, o.course),
			{"exam_session": o.exam_session, "course": o.course, "outcomes": 0, "increased": 0, "decreased": 0, "unchanged": 0,
			"grade_changed": 0, "_total": 0},
		)  # fmt: skip
		direction = change_direction(o.original_ese, o.new_ese)
		row["outcomes"] += 1
		row[{INCREASED: "increased", DECREASED: "decreased", UNCHANGED: "unchanged"}[direction]] += 1
		row["grade_changed"] += int((o.original_grade or "") != (o.revised_grade or ""))
		row["_total"] += flt(o.ese_change)
	out = []
	for row in rows.values():
		row["average_change"] = round(row.pop("_total") / row["outcomes"], 2)
		out.append(row)
	return out
