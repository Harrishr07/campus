"""M07-01, M07-03, M06-08 Faculty pages of /campus-portal (P2-T11): my timetable, attendance for own or substituted
periods, CIA entry, course plan, own leave and mentees.

The caller is the session user's active Employee, never an id from the request. A period is the teacher's own when
its Course Schedule names their Instructor or they instruct its Student Group; a substitute gets exactly the period
of their Confirmed Substitution. CIA entry is for instructors of the sheet's offering (the T13 rule) and saves the
Mark Sheet Entry, whose controller applies the CIA lock. Desk roles such as Academics User widen nothing here.
"""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, today

from campus.examinations.api import cia_lock_state, instructed_offerings, instructor_users, mentees_of
from campus.faculty import substitute_attendance

OWN, SUBSTITUTION = "Own", "Substitution"
TIMETABLE_DAYS, MAX_TIMETABLE_DAYS = 7, 31
SHEET, CIA_SCHEDULE = "Mark Sheet Entry", "CIA Schedule"


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
	return None if user == "Guest" else frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


def require_faculty():
	employee = active_employee()
	if not employee:
		frappe.throw(_("The faculty portal is for staff with an active Employee record."), frappe.PermissionError)
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
	own = frappe.get_all("Course Schedule", {"instructor": ["in", instructors_of(employee) or [""]], "schedule_date": dates}, pluck="name")
	covered = frappe.get_all(
		"Substitution", {"substitute_user": frappe.session.user, "status": substitute_attendance.LIVE_GRANT, "schedule_date": dates}, pluck="course_schedule"
	)
	grants = {**dict.fromkeys(covered, SUBSTITUTION), **dict.fromkeys(own, OWN)}
	periods = [period_row(s, grants[s.name]) for s in schedules(list(grants))]
	return {"from_date": start, "to_date": end, "periods": sorted(periods, key=lambda p: (p["schedule_date"], p["from_time"]))}


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


def own_offerings(employee):
	"""Student Groups the caller instructs, or teaches a scheduled period of."""
	listed = {o for o in instructed_offerings(frappe.session.user) if o}
	taught = frappe.get_all("Course Schedule", {"instructor": ["in", instructors_of(employee) or [""]]}, pluck="student_group", distinct=True)
	return sorted(listed | set(taught))


# ---- attendance -------------------------------------------------------------------------------


def period_grant(course_schedule, employee):
	"""Own or Substitution when the caller may mark this period; PermissionError otherwise."""
	schedule = frappe.db.get_value("Course Schedule", course_schedule, ["instructor", "student_group"], as_dict=True)
	if schedule and (schedule.instructor in instructors_of(employee) or schedule.student_group in instructed_offerings(frappe.session.user)):
		return OWN
	if schedule and substitute_attendance.granting_substitution(frappe.session.user, course_schedule):
		return SUBSTITUTION
	frappe.throw(_("This period is neither yours nor substituted to you."), frappe.PermissionError)


@frappe.whitelist()
def attendance_roll(course_schedule):
	"""The period, the caller's grant and the active students of its group with any status marked."""
	grant = period_grant(course_schedule, require_faculty())
	schedule = schedules([course_schedule])[0]
	marked = dict(
		frappe.get_all("Student Attendance", {"course_schedule": course_schedule, "docstatus": 1}, ["student", "status"], as_list=True)
	)
	students = [
		{"student": s.student, "student_name": s.student_name, "roll": s.group_roll_number, "status": marked.get(s.student)}
		for s in roll(schedule.student_group)
	]
	return {"period": period_row(schedule, grant), "grant": grant, "students": students}


@frappe.whitelist(methods=["POST"])
def mark_attendance(course_schedule, absent=None):
	"""Mark the period: the listed students Absent, every other active student of the group Present."""
	period_grant(course_schedule, require_faculty())
	absent = substitute_attendance.as_list(absent)
	group = frappe.db.get_value("Course Schedule", course_schedule, "student_group")
	present = list(dict.fromkeys(s.student for s in roll(group) if s.student not in absent))
	substitute_attendance.mark_period(course_schedule, present, absent)
	return {"present": len(present), "absent": len(absent)}


def roll(student_group):
	return frappe.get_all(
		"Student Group Student", {"parent": student_group, "parenttype": "Student Group", "active": 1},
		["student", "student_name", "group_roll_number"], order_by="group_roll_number, student",
	)  # fmt: skip


# ---- CIA (M06-08) -----------------------------------------------------------------------------


@frappe.whitelist()
def my_mark_sheets():
	"""Mark Sheet Entries of the offerings the caller instructs."""
	require_faculty()
	offerings = [o for o in instructed_offerings(frappe.session.user) if o]
	sheets = frappe.get_all(
		SHEET, {"course_offering": ["in", offerings or [""]]}, ["name", "exam_session", "course_offering", "course"], order_by="exam_session, course_offering"
	)
	for sheet in sheets:
		sheet.session_status = frappe.db.get_value("Exam Session", sheet.exam_session, "status")
	return sheets


def own_sheet(mark_sheet, ptype):
	require_faculty()
	offering = frappe.db.get_value(SHEET, mark_sheet, "course_offering")
	if not offering or frappe.session.user not in instructor_users(offering):
		frappe.throw(_("You do not instruct this offering."), frappe.PermissionError)
	doc = frappe.get_doc(SHEET, mark_sheet)
	doc.check_permission(ptype)
	return doc


@frappe.whitelist()
def cia_sheet(mark_sheet):
	"""The sheet's students with their CIA question marks (or CIA column), the lock state and whether it is editable."""
	doc = own_sheet(mark_sheet, "read")
	schedule = frappe.db.get_value(CIA_SCHEDULE, {"course_offering": doc.course_offering})
	lock_state = cia_lock_state(schedule) if schedule else None
	published = frappe.db.get_value("Exam Session", doc.exam_session, "status") == "Published"
	questions = cia_questions(schedule)
	cells = {(r.student, r.component, r.question): r for r in doc.get("cia_marks", [])}
	students = []
	for row in doc.marks:
		marks = [cells.get((row.student, q.component, q.question)) for q in questions]
		students.append(
			{
				"student": row.student, "student_name": row.student_name, "cia": row.cia, "cia_attendance": row.cia_attendance,
				"marks": [{"marks": m.marks if m else None, "absent": m.absent if m else 0} for m in marks],
			}
		)  # fmt: skip
	return {
		"name": doc.name, "exam_session": doc.exam_session, "course_offering": doc.course_offering, "course": doc.course,
		"cia_schedule": schedule, "lock_state": lock_state, "editable": not published and lock_state != "Locked",
		"questions": questions, "students": students,
	}  # fmt: skip


def cia_questions(schedule):
	if not schedule:
		return []
	return frappe.get_all(
		"CIA Schedule Question", {"parent": schedule, "parenttype": CIA_SCHEDULE}, ["component", "question", "max_marks"], order_by="idx"
	)


@frappe.whitelist(methods=["POST"])
def save_cia_marks(mark_sheet, marks):
	"""Save CIA marks on the caller's own sheet: rows of {student, component, question, marks, absent} under a CIA
	Schedule, else {student, cia}. The Mark Sheet Entry controller checks ranges and refuses edits once locked."""
	doc = own_sheet(mark_sheet, "write")
	rows = frappe.parse_json(marks) if isinstance(marks, str) else marks
	if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
		frappe.throw(_("Give the marks as a list of rows."))
	schedule = frappe.db.get_value(CIA_SCHEDULE, {"course_offering": doc.course_offering})
	(apply_question_marks if schedule else apply_cia_column)(doc, rows, schedule)
	doc.save()
	return {row.student: row.cia for row in doc.marks}


def apply_question_marks(doc, rows, schedule):
	students = {r.student for r in doc.marks}
	questions = {(q.component, q.question) for q in cia_questions(schedule)}
	cells = {(r.student, r.component, r.question): r for r in doc.get("cia_marks", [])}
	for row in rows:
		key = (row.get("student"), row.get("component"), row.get("question"))
		if key[0] not in students or key[1:] not in questions:
			frappe.throw(_("No CIA question {1} {2} for {0} on this sheet.").format(*key))
		values = {"marks": flt(row.get("marks")), "absent": cint(row.get("absent"))}
		if key in cells:
			cells[key].update(values)
		else:  # the controller's sync adds the CO / Bloom tags
			doc.append("cia_marks", {"student": key[0], "component": key[1], "question": key[2], **values})


def apply_cia_column(doc, rows, _schedule):
	by_student = {r.student: r for r in doc.marks}
	for row in rows:
		if row.get("student") not in by_student:
			frappe.throw(_("{0} is not on this sheet.").format(row.get("student")))
		by_student[row["student"]].cia = flt(row.get("cia"))


# ---- course plan, mentees, leave --------------------------------------------------------------


@frappe.whitelist()
def course_plan():
	"""Read-only: per own offering, the curriculum periods a week, periods scheduled and held so far, and the topics."""
	employee = require_faculty()
	return [plan_row(offering) for offering in own_offerings(employee)]


def plan_row(offering):
	group = frappe.db.get_value("Student Group", offering, ["course", "academic_term", "oc_curriculum"], as_dict=True)
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
	students = frappe.get_all("Student", {"name": ["in", list(mentees_of(frappe.session.user)) or [""]]}, ["name", "student_name"], order_by="student_name, name")
	return [{"student": s.name, "student_name": s.student_name, "program": current_program(s.name)} for s in students]


def current_program(student):
	return frappe.db.get_value("Program Enrollment", {"student": student, "docstatus": 1}, "program", order_by="enrollment_date desc")


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
