"""P2-T11 (M07, M06-08) API permission tests for the faculty pages of /campus-portal: my timetable, attendance for own
or substituted periods (bulk present with exceptions, 60 students), CIA entry on the teacher's own Mark Sheet Entry
under the T13 lock (test_faculty_portal_cia), course plan, own leave on HRMS and read-only mentees. Every action is refused to a student, to
another teacher's offering, and (substitutes) to any period but the substituted one.

Fixtures: the T08 substitution fixture (T07 timetable published from Monday 2026-11-16).
"""

import time
from unittest import mock

import frappe
from frappe.utils import set_request
from frappe.website.serve import get_response_without_exception_handling

from campus.faculty import portal
from campus.tests import demo
from campus.tests.test_substitution import (
	DEFAULT_COMPANY,
	FIRST,
	SECOND,
	SUB_USER,
	SubstitutionFixture,
	submit_leave,
)
from campus.tests.test_timetable import employee
from campus.www.campus_portal.faculty import attendance as attendance_page

TEACHER, COLLEAGUE, STUDENT = demo.email("faculty_1"), demo.email("faculty_2"), demo.email("student_1")
TODAY = "2026-11-20"  # after the fixture's periods


class FacultyPortalFixture(SubstitutionFixture):
	def setUp(self):
		super().setUp()
		for target, value in (
			(DEFAULT_COMPANY, demo.ENGINEERING),
			("campus.faculty.substitute_attendance.today", TODAY),
		):
			patcher = mock.patch(
				target, return_value=value
			)  # the test site has no default company; periods are past
			patcher.start()
			self.addCleanup(patcher.stop)

	def period_of(self, username):
		"""The teacher's first published period (the solver decides the weekday)."""
		instructor = frappe.db.get_value("Instructor", {"employee": employee(username)})
		return frappe.get_all(
			"Course Schedule", {"instructor": instructor, "schedule_date": ["between", [FIRST, TODAY]]},
			["name", "student_group"], order_by="schedule_date, from_time", limit=1,
		)[0]  # fmt: skip

	def enrol(self, group, students):
		for n, student in enumerate(students, 1):
			frappe.get_doc(
				{
					"doctype": "Student Group Student", "parent": group, "parenttype": "Student Group", "parentfield": "students",
					"student": student, "student_name": student, "group_roll_number": n, "active": 1,
				}
			).insert(ignore_permissions=True)  # fmt: skip

	def attendance(self, schedule):
		return dict(
			frappe.get_all(
				"Student Attendance",
				{"course_schedule": schedule, "docstatus": 1},
				["student", "status"],
				as_list=True,
			)
		)

	def as_user(self, user, fn, *args, **kwargs):
		frappe.set_user(user)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def mark(self, user, schedule, absent):
		"""Open the roll and post it, as the page does (the roll's version token goes back with the marks)."""
		version = self.as_user(user, portal.attendance_roll, schedule)["version"]
		return self.as_user(user, portal.mark_attendance, schedule, absent=absent, version=version)

	def co_instruct(self, username, group):
		instructor = frappe.db.get_value("Instructor", {"employee": employee(username)})
		frappe.get_doc(
			{"doctype": "Student Group Instructor", "parent": group, "parenttype": "Student Group", "parentfield": "instructors", "instructor": instructor}
		).insert(ignore_permissions=True)  # fmt: skip


class TestAttendance(FacultyPortalFixture):
	def setUp(self):
		super().setUp()
		self.own = self.period_of("faculty_1")
		self.others = self.period_of("faculty_2")
		self.students = frappe.get_all("Student", pluck="name", limit=3, order_by="name")
		for period in (self.own, self.others):
			self.enrol(period.student_group, self.students)

	def test_a_teacher_marks_their_own_period_all_present_but_the_exceptions(self):
		result = self.mark(TEACHER, self.own.name, frappe.as_json([self.students[1]]))
		self.assertEqual(result, {"present": 2, "absent": 1})
		self.assertEqual(
			self.attendance(self.own.name),
			{self.students[0]: "Present", self.students[1]: "Absent", self.students[2]: "Present"},
		)

	def test_remarking_corrects_only_the_changed_students(self):
		self.mark(TEACHER, self.own.name, [])
		self.mark(TEACHER, self.own.name, [self.students[0]])
		self.assertEqual(self.attendance(self.own.name)[self.students[0]], "Absent")
		self.assertEqual(
			frappe.db.count("Student Attendance", {"course_schedule": self.own.name, "docstatus": 2}), 1
		)

	def test_a_stale_roll_is_refused_and_the_newer_marks_stay(self):
		self.co_instruct("faculty_2", self.own.student_group)  # both teachers may mark this period
		stale = self.as_user(COLLEAGUE, portal.attendance_roll, self.own.name)["version"]
		self.mark(TEACHER, self.own.name, [self.students[0]])
		with self.assertRaises(frappe.ValidationError) as caught:
			self.as_user(COLLEAGUE, portal.mark_attendance, self.own.name, absent=[], version=stale)
		self.assertIn("reload", str(caught.exception).lower())
		self.assertEqual(self.attendance(self.own.name)[self.students[0]], "Absent")

	def test_a_post_without_the_roll_version_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.as_user(
				TEACHER, portal.mark_attendance, self.own.name, absent=[], version="1:2020-01-01 00:00:00"
			)
		self.mark(TEACHER, self.own.name, [])
		with self.assertRaises(frappe.ValidationError):
			self.as_user(TEACHER, portal.mark_attendance, self.own.name, absent=[], version=None)

	def test_an_offering_instructor_owns_its_periods_everywhere(self):
		self.co_instruct("faculty_1", self.others.student_group)
		date = frappe.db.get_value("Course Schedule", self.others.name, "schedule_date")
		listed = self.as_user(TEACHER, portal.my_timetable, from_date=date, to_date=date)["periods"]
		self.assertIn((self.others.name, "Own"), [(p["course_schedule"], p["grant"]) for p in listed])
		self.assertEqual(self.as_user(TEACHER, portal.attendance_roll, self.others.name)["grant"], "Own")
		self.assertIn(
			self.others.student_group, [row["offering"] for row in self.as_user(TEACHER, portal.course_plan)]
		)

	def test_another_teachers_period_is_refused_whatever_the_desk_roles(self):
		self.assertIn(
			"Academics User", frappe.get_roles(TEACHER)
		)  # desk may mark any attendance; the portal may not
		for call in (portal.mark_attendance, portal.attendance_roll):
			with self.assertRaises(frappe.PermissionError):
				self.as_user(
					TEACHER,
					call,
					self.others.name,
					**({"absent": []} if call is portal.mark_attendance else {}),
				)
		self.assertEqual(self.attendance(self.others.name), {})

	def test_the_roll_shows_the_group_with_the_marked_status(self):
		self.mark(TEACHER, self.own.name, [self.students[2]])
		roll = self.as_user(TEACHER, portal.attendance_roll, self.own.name)
		self.assertEqual(roll["grant"], "Own")
		self.assertEqual(
			[(s["student"], s["status"]) for s in roll["students"]],
			[(s, "Absent" if s == self.students[2] else "Present") for s in self.students],
		)

	def test_an_absentee_outside_the_group_is_refused(self):
		outsider = frappe.get_all("Student", {"name": ["not in", self.students]}, pluck="name", limit=1)
		with self.assertRaises(frappe.ValidationError):
			self.mark(TEACHER, self.own.name, outsider)
		self.assertEqual(self.attendance(self.own.name), {})

	def test_a_student_is_refused_every_faculty_action(self):
		calls = [
			(portal.my_timetable, {}), (portal.attendance_roll, {"course_schedule": self.own.name}),
			(portal.mark_attendance, {"course_schedule": self.own.name, "absent": []}),
			(portal.course_plan, {}), (portal.my_leaves, {}), (portal.my_mentees, {}),
			(portal.apply_leave, {"leave_type": "x", "from_date": FIRST, "to_date": FIRST}),
		]  # fmt: skip
		for call, kwargs in calls:
			with self.assertRaises(frappe.PermissionError, msg=call.__name__):
				self.as_user(STUDENT, call, **kwargs)
			with self.assertRaises(frappe.PermissionError, msg=call.__name__):
				self.as_user("Guest", call, **kwargs)
		self.assertEqual(self.attendance(self.own.name), {})

	def test_the_attendance_page_renders_the_roll_escaped(self):
		frappe.db.set_value(
			"Student Group Student",
			{"parent": self.own.student_group, "student": self.students[0]},
			"student_name",
			"<script>x</script>",
		)
		frappe.set_user(TEACHER)
		set_request(method="GET", path="/campus-portal/faculty/attendance")
		with mock.patch.dict(frappe.local.form_dict, {"course_schedule": self.own.name}):
			html = frappe.safe_decode(get_response_without_exception_handling().get_data())
		self.assertIn("&lt;script&gt;x&lt;/script&gt;", html)
		self.assertNotIn("<script>x</script>", html)
		self.assertEqual(html.count('name="absent"'), len(self.students))
		self.assertIn(f'name="version" value="{portal.marks_version(self.own.name)}"', html)

	def test_every_faculty_page_renders_for_a_teacher_and_turns_a_student_away(self):
		pages = (
			"/campus-portal/faculty",
			*(
				f"/campus-portal/faculty/{p}"
				for p in ("attendance", "cia", "course-plan", "leave", "mentees")
			),
		)
		for user, expected in ((TEACHER, "cp-nav"), (STUDENT, "active Employee record")):
			frappe.set_user(user)
			for path in pages:
				set_request(method="GET", path=path)
				response = get_response_without_exception_handling()
				self.assertEqual(response.status_code, 200, path)
				self.assertIn(expected, frappe.safe_decode(response.get_data()), (user, path))

	def test_a_guest_is_sent_to_login(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.Redirect):
			attendance_page.get_context(frappe._dict())

	def test_every_write_accepts_post_only(self):
		for method in (portal.mark_attendance, portal.apply_leave):
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[method], ["POST"])

	def test_sixty_students_are_marked_in_one_request(self):
		group = self.own.student_group
		frappe.db.delete("Student Group Student", {"parent": group})
		students = [make_bare_student(n) for n in range(60)]
		self.enrol(group, students)
		absent = students[::7]  # 9 exceptions
		started = time.monotonic()
		result = self.mark(TEACHER, self.own.name, frappe.as_json(absent))
		self.assertLess(time.monotonic() - started, 60)
		self.assertEqual(result, {"present": 51, "absent": 9})
		marked = self.attendance(self.own.name)
		self.assertEqual(len(marked), 60)
		self.assertEqual({s for s, status in marked.items() if status == "Absent"}, set(absent))


class TestSubstitutePeriods(FacultyPortalFixture):
	def setUp(self):
		super().setUp()
		self.substitute = self.make_sub_only_teacher()
		submit_leave(self.hod, FIRST, SECOND)
		self.mine, self.other = self.substitutions()[:2]
		for row, status in ((self.mine, "Confirmed"), (self.other, "Proposed")):
			frappe.db.set_value(
				"Substitution",
				row.name,
				{"substitute": self.substitute, "substitute_user": SUB_USER, "status": status},
			)
		self.students = frappe.get_all("Student", pluck="name", limit=2, order_by="name")
		for group in {
			frappe.db.get_value("Course Schedule", row.course_schedule, "student_group")
			for row in (self.mine, self.other)
		}:
			self.enrol(group, self.students)

	def test_the_substitute_marks_the_substituted_period(self):
		self.assertEqual(
			self.as_user(SUB_USER, portal.attendance_roll, self.mine.course_schedule)["grant"], "Substitution"
		)
		self.mark(SUB_USER, self.mine.course_schedule, [])
		self.assertEqual(self.attendance(self.mine.course_schedule), dict.fromkeys(self.students, "Present"))

	def test_the_substitute_is_refused_any_other_period(self):
		own_of_colleague = self.period_of("faculty_2")
		for schedule in (self.other.course_schedule, own_of_colleague.name):  # only proposed; never theirs
			with self.assertRaises(frappe.PermissionError):
				self.as_user(SUB_USER, portal.mark_attendance, schedule, absent=[], version=None)
			self.assertEqual(self.attendance(schedule), {})

	def test_the_timetable_lists_own_and_substituted_periods_only(self):
		periods = self.as_user(SUB_USER, portal.my_timetable, from_date=FIRST, to_date=SECOND)["periods"]
		self.assertEqual(
			[(p["course_schedule"], p["grant"]) for p in periods],
			[(self.mine.course_schedule, "Substitution")],
		)
		own = self.as_user(TEACHER, portal.my_timetable, from_date=FIRST, to_date=SECOND)["periods"]
		instructor = frappe.db.get_value("Instructor", {"employee": employee("faculty_1")})
		expected = frappe.get_all(
			"Course Schedule",
			{"instructor": instructor, "schedule_date": ["between", [FIRST, SECOND]]},
			pluck="name",
			order_by="schedule_date, from_time",
		)
		self.assertEqual([p["course_schedule"] for p in own], expected)
		self.assertEqual({p["grant"] for p in own}, {"Own"})


class TestCoursePlanMenteesAndLeave(FacultyPortalFixture):
	def test_the_course_plan_lists_own_offerings_only(self):
		plan = self.as_user(TEACHER, portal.course_plan)
		instructor = frappe.db.get_value("Instructor", {"employee": employee("faculty_1")})
		mine = set(
			frappe.get_all(
				"Course Schedule", {"instructor": instructor}, pluck="student_group", distinct=True
			)
		)
		self.assertEqual({row["offering"] for row in plan}, mine)
		self.assertTrue(all(row["scheduled"] > 0 for row in plan))

	def test_mentees_are_the_teachers_own_read_only(self):
		students = frappe.get_all("Student", pluck="name", limit=3, order_by="name")
		frappe.db.set_value("Student", students[0], "oc_mentor", employee("faculty_1"))
		frappe.db.set_value("Student", students[1], "oc_mentor", employee("faculty_2"))
		self.assertEqual([m["student"] for m in self.as_user(TEACHER, portal.my_mentees)], [students[0]])

	def setUp(self):
		super().setUp()
		frappe.get_doc("User", TEACHER).add_roles("Employee")  # HRMS's own right to apply
		frappe.db.set_value("Employee", employee("faculty_1"), "leave_approver", demo.email("principal"))

	def test_leave_is_applied_for_the_caller_only(self):
		leave_type = demo.get_or_insert(
			"Leave Type", {"leave_type_name": "TT Substitution LWP"}, {"is_lwp": 1}
		)
		# frappe.call drops arguments the method does not take, as the HTTP handler does: a posted employee is ignored
		kwargs = {
			"leave_type": leave_type,
			"from_date": FIRST,
			"to_date": FIRST,
			"reason": "Conference",
			"employee": employee("faculty_2"),
		}
		name = self.as_user(TEACHER, frappe.call, portal.apply_leave, **kwargs)
		leave = frappe.get_doc("Leave Application", name)
		self.assertEqual((leave.employee, leave.status, leave.docstatus), (employee("faculty_1"), "Open", 0))
		self.assertEqual([row["name"] for row in self.as_user(TEACHER, portal.my_leaves)], [name])
		self.assertEqual(self.as_user(COLLEAGUE, portal.my_leaves), [])

	def test_a_half_day_counts_half_a_day(self):
		leave_type = demo.get_or_insert(
			"Leave Type", {"leave_type_name": "TT Substitution LWP"}, {"is_lwp": 1}
		)
		name = self.as_user(TEACHER, portal.apply_leave, leave_type, FIRST, FIRST, half_day=1)
		self.assertEqual(
			frappe.db.get_value("Leave Application", name, ["half_day", "total_leave_days"]), (1, 0.5)
		)


def make_bare_student(n):
	"""A Student row without Education's user and customer side effects (only the roll and attendance need it)."""
	doc = frappe.get_doc(
		{
			"doctype": "Student",
			"first_name": f"Bulk {n}",
			"student_email_id": f"t11-bulk-{n}@example.com",
			"enabled": 1,
		}
	)
	doc.set_new_name()
	doc.db_insert()
	return doc.name
