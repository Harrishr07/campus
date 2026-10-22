"""M17-06 Exam Registration Summary: per exam session and program, the Exam Registrations (confirmed, attendance
shortage, detained, debarred) and their courses (current, arrear, not eligible).

Limited to the companies the user is permitted for and to the registrations the user may read."""

import frappe
from frappe import _

from campus.examinations import coe_reports

COUNTS = ("registrations", "confirmed", "shortage", "detained", "debarred", "current_courses", "arrear_courses", "not_eligible_courses")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters) if coe_reports.in_scope(filters.company) else []


def columns():
	labels = {
		"registrations": _("Registrations"), "confirmed": _("Confirmed"), "shortage": _("Attendance Shortage"),
		"detained": _("Detained"), "debarred": _("Debarred"), "current_courses": _("Current Courses"),
		"arrear_courses": _("Arrear Courses"), "not_eligible_courses": _("Not Eligible Courses"),
	}  # fmt: skip
	return [
		{"fieldname": "exam_session", "label": _("Exam Session"), "fieldtype": "Link", "options": "Exam Session", "width": 140},
		{"fieldname": "program", "label": _("Program"), "fieldtype": "Link", "options": "Program", "width": 180},
		*({"fieldname": f, "label": labels[f], "fieldtype": "Int", "width": 120} for f in COUNTS),
	]  # fmt: skip


def data(filters):
	conditions = {"company": filters.company}
	if filters.exam_session:
		conditions["exam_session"] = filters.exam_session
	registrations = frappe.get_list(
		"Exam Registration", filters=conditions,
		fields=["name", "exam_session", "program", "confirmed", "attendance_status", "detained", "debarred"], order_by="name",
	)  # fmt: skip
	courses = frappe.get_all(
		"Exam Registration Course", {"parenttype": "Exam Registration", "parent": ["in", [r.name for r in registrations] or [""]]},
		["parent", "kind", "eligibility"],
	)  # fmt: skip
	key_of = {r.name: (r.exam_session, r.program) for r in registrations}
	out = {}
	for r in registrations:
		row = out.setdefault(key_of[r.name], dict.fromkeys(COUNTS, 0))
		row["registrations"] += 1
		row["confirmed"] += bool(r.confirmed)
		row["shortage"] += r.attendance_status == "Shortage"
		row["detained"] += bool(r.detained)
		row["debarred"] += bool(r.debarred)
	for c in courses:
		row = out[key_of[c.parent]]
		row["current_courses"] += c.kind == "Current"
		row["arrear_courses"] += c.kind == "Arrear"
		row["not_eligible_courses"] += bool(c.eligibility) and c.eligibility != "Eligible"
	return [{"exam_session": s, "program": p, **counts} for (s, p), counts in sorted(out.items(), key=lambda i: (i[0][0], i[0][1] or ""))]
