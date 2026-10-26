"""M06-08 CIA Status by Offering: per course offering with a CIA Schedule, its entry deadline, lock state
(Open, Locked, Unlocked until an approved CIA Unlock Request ends), and the consolidated marks.

Limited to the companies the user is permitted for; offerings follow the CIA Schedule permissions
(instructors their own, an HOD the department's, COE all)."""

import frappe
from frappe import _

from campus.campus_platform.company_scope import permitted_companies
from campus.examinations import cia


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "course_offering", "label": _("Course Offering"), "fieldtype": "Link", "options": "Student Group", "width": 200},
		{"fieldname": "course", "label": _("Course"), "fieldtype": "Link", "options": "Course", "width": 140},
		{"fieldname": "cia_schedule", "label": _("CIA Schedule"), "fieldtype": "Link", "options": "CIA Schedule", "width": 120},
		{"fieldname": "entry_deadline", "label": _("Entry Deadline"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 90},
		{"fieldname": "unlocked_until", "label": _("Unlocked Until"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "mark_sheet", "label": _("Mark Sheet Entry"), "fieldtype": "Link", "options": "Mark Sheet Entry", "width": 120},
		{"fieldname": "students", "label": _("Students"), "fieldtype": "Int", "width": 80},
		{"fieldname": "absent_students", "label": _("Absent in a Component"), "fieldtype": "Int", "width": 100},
		{"fieldname": "average_cia", "label": _("Average CIA"), "fieldtype": "Float", "precision": 2, "width": 100},
		{"fieldname": "cia_max", "label": _("CIA Max"), "fieldtype": "Float", "width": 80},
	]  # fmt: skip


def data(filters):
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and filters.company not in permitted:
		return []
	conditions = {"company": filters.company}
	if filters.academic_term:
		conditions["academic_term"] = filters.academic_term
	schedules = frappe.get_list(
		cia.SCHEDULE, filters=conditions, fields=["name", "course_offering", "course", "template", "entry_deadline"],
		order_by="course_offering",
	)  # fmt: skip
	return [schedule_row(schedule) for schedule in schedules]


def schedule_row(schedule):
	state = cia.lock_state(schedule.name)
	unlock = cia.active_unlock(schedule.name) if state == cia.UNLOCKED else None
	sheet = frappe.db.get_value("Mark Sheet Entry", {"cia_schedule": schedule.name})
	marks = (
		frappe.get_all(
			"Mark Sheet Entry Row", {"parent": sheet, "parenttype": "Mark Sheet Entry"}, pluck="cia"
		)
		if sheet
		else []
	)
	absent = frappe.get_all(
		"Mark Sheet CIA Mark", {"parent": sheet, "parenttype": "Mark Sheet Entry", "absent": 1}, pluck="student", distinct=True
	) if sheet else []  # fmt: skip
	return {
		"course_offering": schedule.course_offering,
		"course": schedule.course,
		"cia_schedule": schedule.name,
		"entry_deadline": schedule.entry_deadline,
		"status": _(state),
		"unlocked_until": unlock and frappe.db.get_value(cia.UNLOCK, unlock, "unlock_until"),
		"mark_sheet": sheet,
		"students": len(marks),
		"absent_students": len(absent),
		"average_cia": sum(marks) / len(marks) if marks else None,
		"cia_max": frappe.db.get_value(cia.TEMPLATE, schedule.template, "cia_max"),
	}
