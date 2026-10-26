"""M07-01, M07-03, M06-08 Faculty pages of /campus-portal (P2-T11): my timetable, attendance for own or substituted
periods, CIA entry, course plan, own leave and mentees.

The caller is the session user's active Employee, never an id from the request. A period is the teacher's own when
its Course Schedule names their Instructor or they instruct its Student Group; a substitute gets exactly the period
of their Confirmed Substitution. CIA entry is in campus.faculty.portal_cia. Desk roles such as Academics User widen nothing here.
"""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, getdate, today

from campus.examinations.api import instructed_offerings, mentees_of
from campus.faculty import substitute_attendance

OWN, SUBSTITUTION = "Own", "Substitution"
TIMETABLE_DAYS, MAX_TIMETABLE_DAYS = 7, 31


def page_context(context, active):
	"""Login redirect and the shared parts of a faculty page; returns the caller's Employee or None."""
	context.no_cache = 1
	context.show_sidebar = False
	context.active = active
	if frappe.session.user == "Guest":
		request = getattr(frappe.local, "request", None)
		target = request.path if request else "/campus-portal/faculty"
		frappe.local.flags.redirect_location = f"/login?redirect-to={quote(target)}"
		raise frappe.Redirect
	context.employee = active_employee()
	return context.employee


def active_employee(user=None):
	user = user or frappe.session.user
	return (
		None
		if user == "Guest"
		else frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
	)


def require_faculty():
	employee = active_employee()
	if not employee:
		frappe.throw(
			_("The faculty portal is for staff with an active Employee record."), frappe.PermissionError
		)
	return employee


# ---- timetable --------------------------------------------------------------------------------


@frappe.whitelist()
def my_timetable(from_date=None, to_date=None):
	"""The caller's own and substituted periods from `from_date` (today) for a week, at most a month."""
	employee = require_faculty()
	start = getdate(from_date or today())
	end = getdate(to_date) if to_date else add_days(start, TIMETABLE_DAYS - 1)
	if end < start or date_diff(end, start) >= MAX_TIMETABLE_DAYS:
		frappe.throw(_("Choose a range of up to {0} days.").format(MAX_TIMETABLE_DAYS))
	dates = ["between", [start, end]]
	own = own_schedules(employee, {"schedule_date": dates})
	covered = frappe.get_all(
		"Substitution",
		{
			"substitute_user": frappe.session.user,
			"status": substitute_attendance.LIVE_GRANT,
			"schedule_date": dates,
		},
		pluck="course_schedule",
	)
	grants = {**dict.fromkeys(covered, SUBSTITUTION), **dict.fromkeys(own, OWN)}
	periods = [period_row(s, grants[s.name]) for s in schedules(list(grants))]
	return {
		"from_date": start,
		"to_date": end,
		"periods": sorted(periods, key=lambda p: (p["schedule_date"], p["from_time"])),
	}


def schedules(names):
	fields = ["name", "schedule_date", "from_time", "to_time", "course", "student_group", "room"]
	return frappe.get_all("Course Schedule", {"name": ["in", names or [""]]}, fields)


def period_row(schedule, grant):
	marked = frappe.db.count("Student Attendance", {"course_schedule": schedule.name, "docstatus": 1})
	return {
		"course_schedule": schedule.name, "schedule_date": schedule.schedule_date, "from_time": schedule.from_time,
		"to_time": schedule.to_time, "course": schedule.course, "student_group": schedule.student_group,
		"room": schedule.room, "grant": grant, "marked": marked,
	}  # fmt: skip


def instructors_of(employee):
	return frappe.get_all("Instructor", {"employee": employee}, pluck="name")


def listed_offerings():
	"""Student Groups naming the caller as an instructor (the T13 rule)."""
	return [o for o in instructed_offerings(frappe.session.user) if o]


def own_schedules(employee, filters=None, pluck="name"):
	"""The caller's own periods, one definition for the timetable, attendance and course plan: the Course Schedule
	names their Instructor, or they instruct its Student Group."""
	return frappe.get_all(
		"Course Schedule", filters or {}, pluck=pluck, distinct=True,
		or_filters={"instructor": ["in", instructors_of(employee) or [""]], "student_group": ["in", listed_offerings() or [""]]},
	)  # fmt: skip


def own_offerings(employee):
	"""Student Groups the caller instructs, or teaches a scheduled period of."""
	return sorted(set(listed_offerings()) | set(own_schedules(employee, pluck="student_group")))


# ---- attendance -------------------------------------------------------------------------------


def period_grant(course_schedule, employee):
	"""Own or Substitution when the caller may mark this period; PermissionError otherwise."""
	if own_schedules(employee, {"name": course_schedule}):
		return OWN
	if substitute_attendance.granting_substitution(frappe.session.user, course_schedule):
		return SUBSTITUTION
	frappe.throw(_("This period is neither yours nor substituted to you."), frappe.PermissionError)


@frappe.whitelist()
def attendance_roll(course_schedule):
	"""The period, the caller's grant and the active students of its group with any status marked."""
	grant = period_grant(course_schedule, require_faculty())
	schedule = schedules([course_schedule])[0]
	marked = dict(
		frappe.get_all(
			"Student Attendance",
			{"course_schedule": course_schedule, "docstatus": 1},
			["student", "status"],
			as_list=True,
		)
	)
	students = [
		{
			"student": s.student,
			"student_name": s.student_name,
			"roll": s.group_roll_number,
			"status": marked.get(s.student),
		}
		for s in roll(schedule.student_group)
	]
	return {
		"period": period_row(schedule, grant),
		"grant": grant,
		"students": students,
		"version": marks_version(course_schedule),
	}


@frappe.whitelist(methods=["POST"])
def mark_attendance(course_schedule, absent=None, version=None):
	"""Mark the period: the listed students Absent, every other active student of the group Present. `version` is the
	roll's token: marks saved by someone else since the roll was opened refuse the post instead of being overwritten."""
	period_grant(course_schedule, require_faculty())
	frappe.db.get_value(
		"Course Schedule", course_schedule, "name", for_update=True
	)  # mark_period holds the same lock
	if not version or version != marks_version(course_schedule, for_update=True):
		frappe.throw(
			_(
				"The attendance of this period changed since you opened it. Please reload the page and mark again."
			)
		)
	absent = substitute_attendance.as_list(absent)
	group = frappe.db.get_value("Course Schedule", course_schedule, "student_group")
	present = list(dict.fromkeys(s.student for s in roll(group) if s.student not in absent))
	substitute_attendance.mark_period(course_schedule, present, absent)
	return {"present": len(present), "absent": len(absent)}


def marks_version(course_schedule, for_update=False):
	"""Count and last change of the period's submitted attendance; a locking read after the period lock."""
	count, modified = frappe.db.sql(
		f"""select count(*), max(modified) from `tabStudent Attendance`
		where course_schedule = %s and docstatus = 1{" for update" if for_update else ""}""",
		course_schedule,
	)[0]
	return f"{count}:{modified or ''}"


def roll(student_group):
	return frappe.get_all(
		"Student Group Student", {"parent": student_group, "parenttype": "Student Group", "active": 1},
		["student", "student_name", "group_roll_number"], order_by="group_roll_number, student",
	)  # fmt: skip


# ---- course plan, mentees, leave --------------------------------------------------------------


@frappe.whitelist()
def course_plan():
	"""Read-only: per own offering, the curriculum periods a week, periods scheduled and held so far, and the topics."""
	employee = require_faculty()
	return [plan_row(offering) for offering in own_offerings(employee)]


def plan_row(offering):
	group = frappe.db.get_value(
		"Student Group", offering, ["course", "academic_term", "oc_curriculum"], as_dict=True
	)
	weekly = frappe.db.get_value(
		"Curriculum Course", {"parent": group.oc_curriculum or "", "course": group.course},
		["lecture_periods", "tutorial_periods", "practical_periods"], as_dict=True,
	)  # fmt: skip
	return {
		"offering": offering, "course": group.course, "academic_term": group.academic_term, "weekly": weekly,
		"scheduled": frappe.db.count("Course Schedule", {"student_group": offering}),
		"held": frappe.db.count("Course Schedule", {"student_group": offering, "schedule_date": ["<=", today()]}),
		"topics": frappe.get_all("Course Topic", {"parent": group.course, "parenttype": "Course"}, pluck="topic_name", order_by="idx"),
	}  # fmt: skip


@frappe.whitelist()
def my_mentees():
	"""Read-only: the caller's mentees (Student.oc_mentor) with their current programme."""
	require_faculty()
	students = frappe.get_all(
		"Student",
		{"name": ["in", list(mentees_of(frappe.session.user)) or [""]]},
		["name", "student_name"],
		order_by="student_name, name",
	)
	return [
		{"student": s.name, "student_name": s.student_name, "program": current_program(s.name)}
		for s in students
	]


def current_program(student):
	return frappe.db.get_value(
		"Program Enrollment", {"student": student, "docstatus": 1}, "program", order_by="enrollment_date desc"
	)


@frappe.whitelist()
def leave_types():
	require_faculty()
	return frappe.get_all("Leave Type", pluck="name", order_by="name")


@frappe.whitelist(methods=["POST"])
def apply_leave(leave_type, from_date, to_date, reason=None, half_day=0):
	"""An Open HRMS Leave Application for the caller's own Employee, under HRMS's permissions and rules."""
	from hrms.hr.doctype.leave_application.leave_application import get_employee_leave_approver

	employee = require_faculty()
	half_day = cint(half_day)
	doc = frappe.get_doc(
		{
			"doctype": "Leave Application", "employee": employee, "leave_type": leave_type, "from_date": from_date,
			"to_date": to_date, "half_day": half_day, "half_day_date": from_date if half_day else None,
			"description": reason, "status": "Open", "posting_date": today(),
			"company": frappe.db.get_value("Employee", employee, "company"),
			"leave_approver": get_employee_leave_approver(employee),
		}
	)  # fmt: skip
	return doc.insert().name


@frappe.whitelist()
def my_leaves():
	employee = require_faculty()
	return frappe.get_all(
		"Leave Application", {"employee": employee},
		["name", "leave_type", "from_date", "to_date", "total_leave_days", "status", "docstatus"], order_by="from_date desc",
	)  # fmt: skip
