"""PR-03 The current term (2026-27 Odd) of the 2025 batch, now in its second year: Course Registration for semester 3, offerings
with instructors, continuous internal assessment marks (the end-semester marks are not due yet), and for the CSE class a
timetable (Course Schedules), three weeks of attendance ending the day before the load, one medical leave and one on-duty.

Attendance and leave go through the real documents and their validation (the kit gave the college a Holiday List). A leave is a
submitted Student Leave Application with its certificate; Education's own submit hook then writes the class group's attendance
for the days of the leave, and the student's sessions in those days are marked Leave against the application."""

import frappe
from frappe.utils import add_days, getdate, today

from campus.setup.demo_data import academics
from campus.setup.demo_data.batch import class_group_name
from campus.setup.demo_data.curriculum import semester_courses
from campus.setup.records import upsert

YEAR, TERM_NAME, SEMESTER = "2026-27", "Odd", 3
CLASS_PROGRAMME = "CSE"  # the programme whose class has a timetable and attendance
WEEKS, SESSION_DAYS = 3, (0, 2, 4)  # Monday, Wednesday and Friday, counted back from the load date
ROOM = "Room 101"
PERIODS = ("09:00:00", "09:50:00", "10:50:00", "11:40:00", "13:30:00", "14:20:00")  # start of each of the six courses' period
MEDICAL_STUDENT, MEDICAL_SESSIONS = 2, (3, 4, 5)  # the third CSE student (SXCCE25CSE0003) is on medical leave in the second week
ON_DUTY_STUDENT, ON_DUTY_SESSIONS = 4, (6, 7)  # the fifth (SXCCE25CSE0005) is away for a contest in the third week
CERTIFICATE = {"Medical": "medical-certificate.txt", "On Duty": "on-duty-letter.txt"}


def load(ctx):
	term = academics.term_of(YEAR, TERM_NAME)
	upsert(
		ctx.out, "Registration Window", {"company": ctx.college, "academic_term": term},
		{"opens_on": frappe.db.get_value("Academic Term", term, "term_start_date"), "closes_on": "2026-06-30"},
	)
	session = academics.ensure_session(ctx, term)
	cohort = ctx.cohort
	for programme in ctx.profile["programmes"]:
		students = cohort.students(ctx, programme)
		offerings = academics.make_offerings(ctx, programme, term, SEMESTER)
		academics.register_students(ctx, programme, students, term, SEMESTER)
		academics.enter_marks(ctx, session, offerings, students, cia_only=True)
		if programme["abbr"] == CLASS_PROGRAMME:
			make_timetable_and_attendance(ctx, programme, term, offerings, students)


def session_dates(term):
	"""Monday, Wednesday and Friday of the last WEEKS weeks up to yesterday (kept inside the term): nine dates, oldest first."""
	start, end = (getdate(d) for d in frappe.db.get_value("Academic Term", term, ["term_start_date", "term_end_date"]))
	last = max(min(add_days(getdate(today()), -1), end), add_days(start, 7 * WEEKS - 1))
	days = (add_days(last, -offset) for offset in range(7 * WEEKS - 1, -1, -1))
	return [day for day in days if day.weekday() in SESSION_DAYS]


def make_timetable_and_attendance(ctx, programme, term, offerings, students):
	pending = [offering for offering in offerings.values() if not frappe.db.count("Course Schedule", {"student_group": offering})]
	if not pending:
		return  # built on an earlier load: its dates stay as they were
	dates = session_dates(term)
	room = upsert(ctx.out, "Room", {"room_name": ROOM}, {"room_number": "101", "seating_capacity": "60", "oc_company": ctx.college})
	leave_days = {
		MEDICAL_STUDENT: (dates[MEDICAL_SESSIONS[0]], dates[MEDICAL_SESSIONS[-1]], "Medical"),
		ON_DUTY_STUDENT: (dates[ON_DUTY_SESSIONS[0]], dates[ON_DUTY_SESSIONS[-1]], "On Duty"),
	}
	on_leave = []  # (student, offering, schedule, date, number): marked once the leave is submitted
	for course_number, offering in enumerate(offerings.values()):
		if offering not in pending:
			continue
		instructor = frappe.db.get_value("Student Group Instructor", {"parent": offering}, "instructor")
		for n, date in enumerate(dates):
			schedule = make_schedule(offering, instructor, room, date, course_number)
			ctx.out.created["Course Schedule"] += 1
			for number, student in enumerate(students):
				if number in leave_days and leave_days[number][0] <= date <= leave_days[number][1]:
					on_leave.append((number, student, offering, schedule, date))
				else:
					mark_attendance(ctx, student, offering, schedule, date, absent_at(number, n, course_number))
	class_group = class_group_name(ctx, programme)
	leaves = {number: make_leave(ctx, students[number], class_group, *days) for number, days in leave_days.items()}
	for number, student, offering, schedule, date in on_leave:
		mark_attendance(ctx, student, offering, schedule, date, "Leave", leaves[number])


def absent_at(number, session, course_number):
	"""A few students miss class: a status of "Absent" or "Present"."""
	missed = (number + session * 3 + course_number) % 11 == 0 or (number % 7 == 5 and session % 4 == 1)
	return "Absent" if missed else "Present"


def mark_attendance(ctx, student, offering, schedule, date, status, leave=None):
	"""A submitted Student Attendance through Education's validation (the student must be in the group, the day not a holiday)."""
	frappe.get_doc(
		{
			"doctype": "Student Attendance", "student": student, "student_group": offering, "course_schedule": schedule, "date": date,
			"status": status, "leave_application": leave,
		}
	).insert(ignore_permissions=True).submit()
	ctx.out.created["Student Attendance"] += 1


def make_schedule(offering, instructor, room, date, course_number):
	course = frappe.db.get_value("Student Group", offering, "course")
	start = PERIODS[course_number]
	return frappe.get_doc(
		{
			"doctype": "Course Schedule", "student_group": offering, "course": course, "instructor": instructor, "room": room,
			"schedule_date": date, "from_time": start, "to_time": add_minutes(start, 50),
		}
	).insert(ignore_permissions=True).name


def add_minutes(clock, minutes):
	hours, mins = int(clock[:2]), int(clock[3:5]) + minutes
	return f"{hours + mins // 60:02d}:{mins % 60:02d}:00"


def make_leave(ctx, student, class_group, from_date, to_date, kind):
	"""A submitted Student Leave Application of `kind` with its certificate attached (Medical and On Duty leave need one); the
	class group's attendance for its days is written by Education's own submit hook."""
	name = frappe.db.get_value("Student Leave Application", {"student": student, "from_date": from_date})
	if name:
		return name
	leave = frappe.get_doc(
		{
			"doctype": "Student Leave Application", "student": student, "from_date": from_date, "to_date": to_date, "oc_leave_kind": kind,
			"attendance_based_on": "Student Group", "student_group": class_group, "reason": f"{kind} leave (demo data)",
		}
	).insert(ignore_permissions=True)
	certificate = frappe.get_doc(
		{
			"doctype": "File", "file_name": CERTIFICATE[kind], "content": f"Synthetic {kind} certificate for the demo data.", "is_private": 1,
			"attached_to_doctype": "Student Leave Application", "attached_to_name": leave.name, "attached_to_field": "oc_certificate",
		}
	).insert(ignore_permissions=True)
	leave.reload()
	leave.oc_certificate = certificate.file_url
	leave.submit()
	ctx.out.created["Student Leave Application"] += 1
	return leave.name
