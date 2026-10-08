"""P2-T08 (M07-03) integration tests: approving a Leave Application proposes Substitutions for the absent teacher's
published periods in the leave dates (free faculty of the same department, no clashes), confirming notifies the
substitute, the substitute marks attendance for that period only, and the substitution order prints escaped.

Fixture: the T07 timetable (CSE, sections A and B, published from Monday 2026-11-16). hod_cse is on leave Monday and
Tuesday; faculty_1, faculty_2 and faculty_3 are the other CSE teachers (all Instructors with the Academics User role).
"""

from unittest import mock

import frappe
from frappe.utils import getdate

from campus.faculty import api, substitution
from campus.faculty.timetable import publish
from campus.tests import demo
from campus.tests.test_timetable import CSE, TimetableFixture, employee

FIRST, SECOND = "2026-11-16", "2026-11-17"  # Monday, Tuesday
THIRD = "2026-11-18"
SUB_USER = "sub_only@campus-test.example.com"
EVENT = "substitution.assigned"
DEFAULT_COMPANY = "education.education.doctype.student_attendance.student_attendance.get_default_company"


def make_leave_type():
	return demo.get_or_insert("Leave Type", {"leave_type_name": "TT Substitution LWP"}, {"is_lwp": 1})


def submit_leave(person, from_date, to_date, status="Approved"):
	leave = frappe.get_doc(
		{
			"doctype": "Leave Application", "employee": person, "leave_type": make_leave_type(), "from_date": from_date,
			"to_date": to_date, "status": status, "company": demo.ENGINEERING, "leave_approver": demo.email("principal"), "description": "Conference <b>abroad</b>",
		}
	).insert(ignore_permissions=True)  # fmt: skip
	leave.submit()
	return leave


class SubstitutionFixture(TimetableFixture):
	def setUp(self):
		super().setUp()
		self.assign_holiday_list()
		for username in ("hod_cse", "faculty_1", "faculty_2", "faculty_3"):
			frappe.db.set_value("Employee", employee(username), "department", CSE)
		doc, _run = self.generated()
		publish.publish_now(doc.name, as_of=FIRST)
		self.hod = employee("hod_cse")
		self.hod_instructor = frappe.db.get_value("Instructor", {"employee": self.hod})

	def assign_holiday_list(self):
		"""HRMS needs a holiday list for the leave days; this one has no holidays."""
		holiday_list = demo.get_or_insert("Holiday List", {"holiday_list_name": "TT Substitution No Holidays"}, {"from_date": "2026-01-01", "to_date": "2026-12-31"})
		frappe.db.set_value("Company", demo.ENGINEERING, "default_holiday_list", holiday_list)  # Student Attendance reads the company default
		frappe.get_doc(
			{"doctype": "Holiday List Assignment", "applicable_for": "Company", "assigned_to": demo.ENGINEERING, "holiday_list": holiday_list, "from_date": "2026-01-01"}
		).insert(ignore_permissions=True).submit()  # fmt: skip

	def hod_schedules(self, *dates):
		return frappe.get_all(
			"Course Schedule", {"instructor": self.hod_instructor, "schedule_date": ["in", dates]},
			["name", "student_group", "schedule_date", "from_time", "to_time"], order_by="schedule_date, from_time",
		)  # fmt: skip

	def substitutions(self, **extra):
		return frappe.get_all(
			"Substitution", {"absent_faculty": self.hod, **extra},
			["name", "course_schedule", "substitute", "status", "schedule_date", "from_time", "to_time", "leave_application"],
			order_by="schedule_date, from_time",
		)  # fmt: skip

	def busy_elsewhere(self, person, row):
		"""Other classes (schedules or live substitutions) of `person` overlapping the substituted period."""
		instructor = frappe.db.get_value("Instructor", {"employee": person})
		overlap = {"schedule_date": row.schedule_date, "from_time": ["<", row.to_time], "to_time": [">", row.from_time]}
		classes = frappe.get_all("Course Schedule", {"instructor": instructor, **overlap}, pluck="name")
		covering = frappe.get_all("Substitution", {"substitute": person, "status": ["!=", "Cancelled"], "name": ["!=", row.name], **overlap}, pluck="name")
		return classes + covering

	def make_sub_only_teacher(self):
		"""A CSE teacher with the Instructor role only (not Academics User): the case a substitution has to grant."""
		user = demo.get_or_insert("User", {"email": SUB_USER}, {"first_name": "Sub Only", "enabled": 1, "send_welcome_email": 0})
		frappe.get_doc("User", user).add_roles("Instructor")
		person = frappe.get_doc(
			{
				"doctype": "Employee", "naming_series": "HR-EMP-", "first_name": "Sub Only", "gender": "Female", "date_of_birth": "1985-01-01",
				"date_of_joining": "2018-06-01", "status": "Active", "company": demo.ENGINEERING, "user_id": SUB_USER,
				"department": CSE, "create_user_permission": 0,
			}
		).insert(ignore_permissions=True)  # fmt: skip
		demo.make_instructor("sub_only", person.name)
		return person.name


class TestProposal(SubstitutionFixture):
	def test_a_two_day_leave_proposes_a_substitute_for_every_period_without_clashes(self):
		periods = self.hod_schedules(FIRST, SECOND)
		self.assertGreaterEqual(len(periods), 2)
		leave = submit_leave(self.hod, FIRST, SECOND)
		proposals = self.substitutions()
		self.assertEqual([p.course_schedule for p in proposals], [s.name for s in periods])
		self.assertEqual({p.leave_application for p in proposals}, {leave.name})
		self.assertEqual({p.status for p in proposals}, {"Proposed"})
		colleagues = {employee(u) for u in ("faculty_1", "faculty_2", "faculty_3")}
		for p in proposals:
			self.assertIn(p.substitute, colleagues)
			self.assertEqual(self.busy_elsewhere(p.substitute, p), [], p.name)

	def test_periods_outside_the_leave_dates_get_no_proposal(self):
		submit_leave(self.hod, FIRST, FIRST)
		self.assertEqual({p.schedule_date for p in self.substitutions()}, {getdate(FIRST)})
		self.assertEqual(self.substitutions(schedule_date=getdate(THIRD)), [])

	def test_a_leave_that_is_not_approved_proposes_nothing(self):
		frappe.get_doc(
			{"doctype": "Leave Application", "employee": self.hod, "leave_type": make_leave_type(), "from_date": FIRST, "to_date": SECOND,
			"status": "Open", "company": demo.ENGINEERING, "leave_approver": demo.email("principal")}  # fmt: skip
		).insert(ignore_permissions=True)
		self.assertEqual(self.substitutions(), [])

	def test_proposing_twice_creates_nothing_new(self):
		leave = submit_leave(self.hod, FIRST, SECOND)
		before = len(self.substitutions())
		self.assertEqual(substitution.propose_for_leave(leave), [])
		self.assertEqual(len(self.substitutions()), before)

	def test_a_colleague_teaching_at_that_time_is_not_suggested(self):
		period = self.hod_schedules(FIRST)[0]
		busy = frappe.get_all(
			"Course Schedule", {"schedule_date": FIRST, "from_time": period.from_time, "instructor": ["!=", self.hod_instructor]}, pluck="instructor"
		)
		busy_people = {frappe.db.get_value("Instructor", i, "employee") for i in busy}
		self.assertTrue(busy_people, "fixture: someone else teaches in the same period")
		suggested = {s["employee"] for s in substitution.free_faculty(period.name)}
		self.assertFalse(busy_people & suggested)
		self.assertTrue(suggested)

	def test_a_colleague_on_approved_leave_is_not_suggested(self):
		period = self.hod_schedules(FIRST)[0]
		free = {s["employee"] for s in substitution.free_faculty(period.name)}
		away = sorted(free)[0]
		submit_leave(away, FIRST, FIRST)
		self.assertNotIn(away, {s["employee"] for s in substitution.free_faculty(period.name)})

	def test_the_absent_teacher_and_other_departments_are_not_suggested(self):
		period = self.hod_schedules(FIRST)[0]
		outsider = employee("faculty_3")
		frappe.db.set_value("Employee", outsider, "department", f"{demo.ECE_DEPARTMENT} - DCE")
		frappe.db.set_value("Instructor", {"employee": outsider}, "department", f"{demo.ECE_DEPARTMENT} - DCE")
		suggested = {s["employee"] for s in substitution.free_faculty(period.name)}
		self.assertNotIn(self.hod, suggested)
		self.assertNotIn(outsider, suggested)

	def test_a_period_has_one_live_substitution(self):
		submit_leave(self.hod, FIRST, FIRST)
		covered = self.substitutions()[0]
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Substitution", "course_schedule": covered.course_schedule}).insert()

	def test_a_clashing_substitute_cannot_be_chosen_by_hand(self):
		period = self.hod_schedules(FIRST)[0]
		busy = frappe.get_all("Course Schedule", {"schedule_date": FIRST, "from_time": period.from_time, "instructor": ["!=", self.hod_instructor]}, pluck="instructor")
		clash = frappe.db.get_value("Instructor", busy[0], "employee")
		with self.assertRaises(frappe.ValidationError) as caught:
			frappe.get_doc({"doctype": "Substitution", "course_schedule": period.name, "substitute": clash}).insert()
		self.assertIn("clash", str(caught.exception).lower())

	def test_cancelling_the_leave_cancels_its_substitutions(self):
		leave = submit_leave(self.hod, FIRST, SECOND)
		first = self.substitutions()[0]
		doc = frappe.get_doc("Substitution", first.name)
		doc.status = "Confirmed"
		doc.save()
		leave.cancel()
		self.assertEqual({p.status for p in self.substitutions()}, {"Cancelled"})


class TestConfirmation(SubstitutionFixture):
	def proposed(self):
		submit_leave(self.hod, FIRST, FIRST)
		return frappe.get_doc("Substitution", self.substitutions()[0].name)

	def test_confirming_notifies_the_substitute_once(self):
		doc = self.proposed()
		self.assertFalse(frappe.get_all("Message Log", {"event_key": EVENT, "reference_name": doc.name}))
		doc.status = "Confirmed"
		doc.save()
		logs = frappe.get_all("Message Log", {"event_key": EVENT, "reference_name": doc.name}, ["recipient"])
		self.assertTrue(logs)
		self.assertTrue(all(doc.substitute in log.recipient for log in logs))
		doc.reload()
		doc.reason = "Edited"
		doc.save()
		self.assertEqual(len(frappe.get_all("Message Log", {"event_key": EVENT, "reference_name": doc.name})), len(logs))

	def test_confirming_needs_a_substitute(self):
		doc = self.proposed()
		doc.substitute = None
		doc.status = "Confirmed"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_a_cancelled_substitution_stays_cancelled(self):
		doc = self.proposed()
		doc.status = "Cancelled"
		doc.save()
		doc.status = "Confirmed"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_the_order_prints_with_the_reason_escaped(self):
		doc = self.proposed()
		frappe.db.set_value("Substitution", doc.name, "reason", "<script>alert(1)</script>")  # as if stored by an import: save() would sanitise it
		html = frappe.get_print("Substitution", doc.name, "Substitution Order")
		self.assertNotIn("<script>alert(1)</script>", html)
		self.assertIn("&lt;script&gt;", html)
		self.assertIn(doc.name, html)


class TestSubstituteAttendance(SubstitutionFixture):
	def setUp(self):
		super().setUp()
		self.substitute = self.make_sub_only_teacher()
		submit_leave(self.hod, FIRST, SECOND)
		self.mine, self.other = self.substitutions()[:2]
		for row in (self.mine, self.other):
			self.assign(row, self.substitute)
		frappe.db.set_value("Substitution", self.mine.name, "status", "Confirmed")
		self.students = self.enrol(self.mine.course_schedule)
		patcher = mock.patch(DEFAULT_COMPANY, return_value=demo.ENGINEERING)  # the test site has no default company, which attendance's holiday check reads
		patcher.start()
		self.addCleanup(patcher.stop)

	def assign(self, row, person):
		frappe.db.set_value("Substitution", row.name, {"substitute": person, "substitute_user": frappe.db.get_value("Employee", person, "user_id")})

	def enrol(self, schedule):
		group = frappe.db.get_value("Course Schedule", schedule, "student_group")
		students = frappe.get_all("Student", pluck="name", limit=3, order_by="name")
		for n, student in enumerate(students, 1):
			frappe.get_doc(
				{
					"doctype": "Student Group Student", "parent": group, "parenttype": "Student Group", "parentfield": "students",
					"student": student, "student_name": student, "group_roll_number": n, "active": 1,
				}
			).insert(ignore_permissions=True)  # fmt: skip
		return students

	def attendance(self, schedule):
		return frappe.get_all("Student Attendance", {"course_schedule": schedule, "docstatus": 1}, ["student", "status"], order_by="student")

	def test_the_confirmed_substitute_marks_attendance_for_that_period(self):
		self.assertTrue(api.can_mark_substituted_attendance(SUB_USER, self.mine.course_schedule))
		frappe.set_user(SUB_USER)
		api.mark_substituted_attendance(self.mine.name, present=self.students[:2], absent=self.students[2:])
		frappe.set_user("Administrator")
		self.assertEqual(
			[(r.student, r.status) for r in self.attendance(self.mine.course_schedule)],
			[(self.students[0], "Present"), (self.students[1], "Present"), (self.students[2], "Absent")],
		)

	def test_no_access_to_another_period_even_one_proposed_for_them(self):
		self.assertFalse(api.can_mark_substituted_attendance(SUB_USER, self.other.course_schedule))
		frappe.set_user(SUB_USER)
		with self.assertRaises(frappe.PermissionError):
			api.mark_substituted_attendance(self.other.name, present=self.students, absent=[])
		frappe.set_user("Administrator")
		self.assertEqual(self.attendance(self.other.course_schedule), [])

	def test_someone_else_cannot_use_the_substitution(self):
		self.assertFalse(api.can_mark_substituted_attendance("faculty_1@" + demo.DOMAIN, self.mine.course_schedule))
		frappe.set_user("faculty_1@" + demo.DOMAIN)
		with self.assertRaises(frappe.PermissionError):
			api.mark_substituted_attendance(self.mine.name, present=self.students, absent=[])

	def test_the_grant_does_not_widen_the_users_roles(self):
		frappe.set_user(SUB_USER)
		self.assertFalse(frappe.has_permission("Student Attendance", "create"))
		self.assertFalse(frappe.has_permission("Course Schedule", "write", self.mine.course_schedule))
		api.mark_substituted_attendance(self.mine.name, present=self.students, absent=[])
		self.assertFalse(frappe.has_permission("Student Attendance", "create"))
		self.assertFalse(set(frappe.get_roles(SUB_USER)) & {"Academics User", "System Manager"})

	def test_only_students_of_the_group_can_be_marked(self):
		outsider = frappe.get_all("Student", {"name": ["not in", self.students]}, pluck="name", limit=1)
		frappe.set_user(SUB_USER)
		with self.assertRaises(frappe.ValidationError):
			api.mark_substituted_attendance(self.mine.name, present=outsider, absent=[])
		frappe.set_user("Administrator")
		self.assertEqual(self.attendance(self.mine.course_schedule), [])

	def test_a_cancelled_or_unconfirmed_substitution_grants_nothing(self):
		frappe.db.set_value("Substitution", self.mine.name, "status", "Cancelled")
		self.assertFalse(api.can_mark_substituted_attendance(SUB_USER, self.mine.course_schedule))
		frappe.set_user(SUB_USER)
		with self.assertRaises(frappe.PermissionError):
			api.mark_substituted_attendance(self.mine.name, present=self.students, absent=[])

	def test_the_substitute_reads_only_their_own_substitutions(self):
		self.assign(self.other, employee("faculty_1"))
		frappe.set_user(SUB_USER)
		self.assertEqual(frappe.get_list("Substitution", pluck="name", order_by="name"), [self.mine.name])
		self.assertFalse(frappe.has_permission("Substitution", "read", self.other.name))
		self.assertFalse(frappe.has_permission("Substitution", "write", self.mine.name))
