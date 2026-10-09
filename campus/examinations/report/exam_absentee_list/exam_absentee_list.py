"""M17-06 Exam Absentee List: the students marked absent on the Seating Plans (the Result Run grades them AB).

Limited to the companies the user is permitted for and to the seating plans the user may read."""

import frappe
from frappe import _

from campus.examinations import coe_reports


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters) if coe_reports.in_scope(filters.company) else []


def columns():
	return [
		{"fieldname": "exam_session", "label": _("Exam Session"), "fieldtype": "Link", "options": "Exam Session", "width": 140},
		{"fieldname": "exam_date", "label": _("Exam Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "slot", "label": _("Slot"), "fieldtype": "Data", "width": 60},
		{"fieldname": "course", "label": _("Course"), "fieldtype": "Link", "options": "Course", "width": 160},
		{"fieldname": "student", "label": _("Student"), "fieldtype": "Link", "options": "Student", "width": 150},
		{"fieldname": "student_name", "label": _("Student Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "room", "label": _("Room"), "fieldtype": "Link", "options": "Room", "width": 120},
		{"fieldname": "seat_label", "label": _("Seat"), "fieldtype": "Data", "width": 70},
	]  # fmt: skip


def data(filters):
	conditions = {"company": filters.company}
	if filters.exam_session:
		conditions["exam_session"] = filters.exam_session
	plans = {p.name: p for p in frappe.get_list("Seating Plan", filters=conditions, fields=["name", "exam_session", "exam_date", "slot"])}
	seats = frappe.get_all(
		"Seating Plan Seat", {"parenttype": "Seating Plan", "parent": ["in", list(plans) or [""]], "absent": 1},
		["parent", "course", "student", "student_name", "room", "seat_label"],
	)  # fmt: skip
	rows = [
		{"exam_session": plans[s.parent].exam_session, "exam_date": plans[s.parent].exam_date, "slot": plans[s.parent].slot,
		**{k: s[k] for k in ("course", "student", "student_name", "room", "seat_label")}}
		for s in seats
	]  # fmt: skip
	return sorted(rows, key=lambda r: (str(r["exam_date"] or ""), r["slot"] or "", r["course"] or "", r["student"] or ""))
