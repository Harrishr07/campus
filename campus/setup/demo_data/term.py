"""PR-03 The current term (2026-27 Odd) of the 2025 batch, now in its second year: Course Registration for semester 3, offerings
with instructors, continuous internal assessment marks (the end-semester marks are not due yet), and for the CSE class a
timetable (Course Schedules), three weeks of attendance, one medical leave and one on-duty."""

import frappe
from frappe.utils import add_days, getdate

from campus.setup.demo_data import academics
from campus.setup.demo_data.batch import Cohort
from campus.setup.demo_data.curriculum import semester_courses
from campus.setup.records import upsert
from campus.tests import demo_slice

YEAR, TERM_NAME, SEMESTER = "2026-27", "Odd", 3
CLASS_PROGRAMME = "CSE"  # the programme whose class has a timetable and attendance
WEEKS, SESSION_DAYS = 3, (0, 2, 4)  # Monday, Wednesday, Friday
ROOM = "Room 101"
PERIODS = ("09:00:00", "09:50:00", "10:50:00", "11:40:00", "13:30:00", "14:20:00")  # start of each of the six courses' period
MEDICAL_STUDENT, MEDICAL_SESSIONS = 2, (3, 4, 5)  # the third CSE student is on medical leave in the second week
ON_DUTY_STUDENT, ON_DUTY_SESSIONS = 4, (6, 7)  # the fifth is away for a contest in the third week


def load(ctx):
	term = academics.term_of(YEAR, TERM_NAME)
	upsert(
		ctx.out, "Registration Window", {"company": ctx.college, "academic_term": term},
		{"opens_on": frappe.db.get_value("Academic Term", term, "term_start_date"), "closes_on": "2026-06-30"},
	)
	session = academics.ensure_session(ctx, term)
	cohort = Cohort(ctx)
	for programme in ctx.profile["programmes"]:
		students = cohort.students(ctx, programme)
		offerings = academics.make_offerings(ctx, programme, term, SEMESTER)
		academics.register_students(ctx, programme, students, term, SEMESTER)
		academics.enter_marks(ctx, session, offerings, students, cia_only=True)
		if programme["abbr"] == CLASS_PROGRAMME:
			make_timetable_and_attendance(ctx, term, offerings, students)


def session_dates(term):
	"""Monday, Wednesday and Friday of the first WEEKS weeks of the term."""
	start = getdate(frappe.db.get_value("Academic Term", term, "term_start_date"))
	monday = add_days(start, -start.weekday()) if start.weekday() == 0 else add_days(start, 7 - start.weekday())
	return [add_days(monday, 7 * week + day) for week in range(WEEKS) for day in SESSION_DAYS]


def make_timetable_and_attendance(ctx, term, offerings, students):
	dates = session_dates(term)
	room = upsert(ctx.out, "Room", {"room_name": ROOM}, {"room_number": "101", "seating_capacity": "60", "oc_company": ctx.college})
	leaves = {
		MEDICAL_STUDENT: make_leave(ctx, students[MEDICAL_STUDENT], dates[MEDICAL_SESSIONS[0]], dates[MEDICAL_SESSIONS[-1]], "Medical"),
		ON_DUTY_STUDENT: make_leave(ctx, students[ON_DUTY_STUDENT], dates[ON_DUTY_SESSIONS[0]], dates[ON_DUTY_SESSIONS[-1]], "On Duty"),
	}
	for course_number, offering in enumerate(offerings.values()):
		if frappe.db.count("Course Schedule", {"student_group": offering}):
			continue
		instructor = frappe.db.get_value("Student Group Instructor", {"parent": offering}, "instructor")
		for n, date in enumerate(dates):
			schedule = make_schedule(offering, instructor, room, date, course_number)
			ctx.out.created["Course Schedule"] += 1
			for number, student in enumerate(students):
				status, leave = attendance_of(number, n, course_number, leaves)
				demo_slice.mark_attendance(student, offering, schedule, date, status, leave)
				ctx.out.created["Student Attendance"] += 1


def attendance_of(number, session, course_number, leaves):
	"""(status, leave application) of a student at a session: the leave students are on leave in their sessions, a few miss class."""
	if number == MEDICAL_STUDENT and session in MEDICAL_SESSIONS:
		return "Leave", leaves[MEDICAL_STUDENT]
	if number == ON_DUTY_STUDENT and session in ON_DUTY_SESSIONS:
		return "Leave", leaves[ON_DUTY_STUDENT]
	absent = (number + session * 3 + course_number) % 11 == 0 or (number % 7 == 5 and session % 4 == 1)
	return ("Absent" if absent else "Present"), None


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


def make_leave(ctx, student, from_date, to_date, kind):
	"""An approved Student Leave Application of `kind` (submitted directly, as the thin-slice demo does: Education's submit hook
	needs a holiday list the college has not set up)."""
	name = frappe.db.get_value("Student Leave Application", {"student": student, "from_date": from_date})
	if name:
		return name
	doc = frappe.get_doc(
		{"doctype": "Student Leave Application", "student": student, "from_date": from_date, "to_date": to_date, "oc_leave_kind": kind}
	)
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True)
	frappe.db.set_value("Student Leave Application", doc.name, "docstatus", 1)
	ctx.out.created["Student Leave Application"] += 1
	return doc.name
