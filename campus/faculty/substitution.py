"""M07-03 Substitution engine: when a Leave Application is approved, every published Course Schedule of the absent
teacher in the leave dates gets a Substitution, proposing a free teacher of the same department.

"Free" is judged with the T07 clash rule (`timetable.rules.clashes`): a teacher is free when no class of theirs
(Course Schedule or live Substitution) overlaps the period, and they are not on approved leave that day.
"""

import frappe
from frappe import _
from frappe.utils import getdate, to_timedelta

from campus.faculty.timetable import rules

LIVE = ("Proposed", "Confirmed")


def seconds(value):
	return int(to_timedelta(value).total_seconds())


def instructor_of(employee):
	return frappe.db.get_value("Instructor", {"employee": employee})


def employee_of_instructor(instructor):
	return frappe.db.get_value("Instructor", instructor, "employee") if instructor else None


# ---- who is free ---------------------------------------------------------------------------


def department_teachers(department):
	"""{employee: employee_name} of active teachers (employees with an Instructor record) whose department is `department`."""
	instructors = frappe.get_all("Instructor", {"employee": ["is", "set"]}, ["employee", "department"])
	employees = frappe.get_all("Employee", {"name": ["in", [i.employee for i in instructors] or [""]], "status": "Active"}, ["name", "employee_name", "department"])
	own = {i.employee: i.department for i in instructors}
	return {e.name: e.employee_name for e in employees if (e.department or own[e.name]) == department}


def on_leave(employee, date):
	"""True when the employee has approved leave covering `date` (a half day counts: they are only partly there)."""
	return bool(
		frappe.db.exists(
			"Leave Application",
			{"employee": employee, "docstatus": 1, "status": "Approved", "from_date": ["<=", date], "to_date": [">=", date]},
		)
	)


def busy_periods(employee, date, ignore=None):
	"""[(from_time, to_time, label)] of the classes the employee takes on `date`: Course Schedules and live Substitutions."""
	taught = frappe.get_all("Course Schedule", {"instructor": instructor_of(employee), "schedule_date": date}, ["name", "from_time", "to_time"])
	covering = frappe.get_all(
		"Substitution", {"substitute": employee, "schedule_date": date, "status": ["in", LIVE], "name": ["!=", ignore or ""]},
		["name", "from_time", "to_time"],
	)  # fmt: skip
	return [(r.from_time, r.to_time, r.name) for r in (*taught, *covering)]


def clashes_with(employee, schedule, ignore=None):
	"""True when the employee already has a class overlapping `schedule` (a row with schedule_date, from_time, to_time)."""
	start, end = seconds(schedule.from_time), seconds(schedule.to_time)
	day = str(getdate(schedule.schedule_date))
	entries = [rules.Entry(schedule.name, schedule.name, employee, "", day, start, "Lecture")]
	for from_time, to_time, label in busy_periods(employee, schedule.schedule_date, ignore):
		overlaps = seconds(from_time) < end and seconds(to_time) > start
		entries.append(rules.Entry(label, label, employee, "", day, start if overlaps else seconds(from_time), "Lecture"))
	return any(v.rule == rules.FACULTY_CLASH for v in rules.clashes(entries))


def schedule_row(course_schedule):
	return frappe.db.get_value("Course Schedule", course_schedule, ["name", "instructor", "schedule_date", "from_time", "to_time", "student_group"], as_dict=True)


def live_count(employee):
	return frappe.db.count("Substitution", {"substitute": employee, "status": ["in", LIVE]})


def free_faculty(course_schedule, ignore=None):
	"""Teachers of the absent teacher's department free for the period, least-covering first: [{employee, employee_name, user}]."""
	schedule = schedule_row(course_schedule)
	absent = employee_of_instructor(schedule.instructor)
	department = frappe.db.get_value("Employee", absent, "department") or frappe.db.get_value("Instructor", schedule.instructor, "department")
	if not department:
		return []
	free = [
		{"employee": employee, "employee_name": name, "user": frappe.db.get_value("Employee", employee, "user_id"), "load": live_count(employee)}
		for employee, name in department_teachers(department).items()
		if employee != absent and not on_leave(employee, schedule.schedule_date) and not clashes_with(employee, schedule, ignore)
	]  # fmt: skip
	return sorted(free, key=lambda f: (f["load"], f["employee"]))


# ---- proposing on approval -----------------------------------------------------------------


def affected_schedules(employee, from_date, to_date):
	instructor = instructor_of(employee)
	if not instructor:
		return []
	return frappe.get_all(
		"Course Schedule", {"instructor": instructor, "schedule_date": ["between", [from_date, to_date]]}, pluck="name", order_by="schedule_date, from_time"
	)


def covered(schedules):
	return set(frappe.get_all("Substitution", {"course_schedule": ["in", schedules or [""]], "status": ["in", LIVE]}, pluck="course_schedule"))


def propose_for_leave(leave):
	"""Create a Substitution for each affected period not already covered; returns the names created. A period with
	nobody free is still listed, with the substitute blank for the HOD to fill."""
	schedules = affected_schedules(leave.employee, leave.from_date, leave.to_date)
	created = []
	for schedule in [s for s in schedules if s not in covered(schedules)]:
		free = free_faculty(schedule)
		reason = _("{0} on leave ({1} to {2})").format(leave.employee_name or leave.employee, leave.from_date, leave.to_date)
		doc = frappe.get_doc(
			{"doctype": "Substitution", "course_schedule": schedule, "leave_application": leave.name, "reason": reason, "substitute": free[0]["employee"] if free else None}
		)
		doc.insert(ignore_permissions=True)
		created.append(doc.name)
	return created


def on_leave_submit(doc, method=None):
	"""Leave Application on_submit: only an Approved leave proposes substitutions. A failure here must not block the
	approval, so it is logged (without context) and the HOD proposes by hand."""
	if doc.status != "Approved":
		return
	frappe.db.savepoint("propose_substitutions")
	try:
		propose_for_leave(doc)
	except Exception:
		frappe.db.rollback(save_point="propose_substitutions")
		frappe.log_error(title=f"Substitution proposals failed for {doc.name}")


def on_leave_cancel(doc, method=None):
	"""A cancelled leave withdraws the substitutions it produced."""
	for name in frappe.get_all("Substitution", {"leave_application": doc.name, "status": ["in", LIVE]}, pluck="name"):
		frappe.db.set_value("Substitution", name, "status", "Cancelled")
