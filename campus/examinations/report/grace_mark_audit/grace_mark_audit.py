"""M06-05 Grace Mark Audit: every grace mark the Result Run gave, per student and course, with the Exam Rule Set
(rule reference) that allowed it and the limits it was given under.

Latest result versions only. Limited to the companies the user is permitted for and to the Student Results the
user may read."""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies

RULE_FIELDS = ["grace_max_per_course", "grace_max_courses", "grace_max_total"]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "student_result", "label": _("Student Result"), "fieldtype": "Link", "options": "Student Result", "width": 200},
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 130},
		{"fieldname": "student_name", "label": _("Name"), "fieldtype": "Data", "width": 160},
		{"fieldname": "exam_session", "label": _("Exam Session"), "fieldtype": "Link", "options": "Exam Session", "width": 110},
		{"fieldname": "course", "label": _("Course"), "fieldtype": "Link", "options": "Course", "width": 130},
		{"fieldname": "ese", "label": _("ESE with Grace"), "fieldtype": "Float", "width": 100},
		{"fieldname": "grace", "label": _("Grace"), "fieldtype": "Float", "width": 80},
		{"fieldname": "grade", "label": _("Grade"), "fieldtype": "Data", "width": 70},
		{"fieldname": "grace_rule", "label": _("Rule"), "fieldtype": "Link", "options": "Exam Rule Set", "width": 140},
		{"fieldname": "rule_limits", "label": _("Limits (per course / courses / total)"), "fieldtype": "Data", "width": 200},
	]  # fmt: skip


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	conditions = {"company": filters.company, "is_latest": 1}
	if filters.exam_session:
		conditions["exam_session"] = filters.exam_session
	results = {
		r.name: r
		for r in frappe.get_list(
			"Student Result", filters=conditions, fields=["name", "student", "student_name", "exam_session"]
		)
	}
	rows = frappe.get_all(
		"Student Result Course",
		{"parenttype": "Student Result", "parent": ["in", list(results) or [""]], "grace": [">", 0]},
		["parent", "course", "ese", "grace", "grade", "grace_rule"],
		order_by="parent, idx",
	)
	limits = {}
	out = []
	for row in rows:
		if row.grace_rule not in limits:
			values = frappe.db.get_value("Exam Rule Set", row.grace_rule, RULE_FIELDS, as_dict=True) or {}
			limits[row.grace_rule] = " / ".join(f"{values.get(f) or 0:g}" for f in RULE_FIELDS)
		result = results[row.parent]
		out.append({
			"student_result": row.parent, "student": result.student, "student_name": result.student_name,
			"exam_session": result.exam_session, "course": row.course, "ese": row.ese, "grace": row.grace,
			"grade": row.grade, "grace_rule": row.grace_rule, "rule_limits": limits[row.grace_rule],
		})  # fmt: skip
	return out
