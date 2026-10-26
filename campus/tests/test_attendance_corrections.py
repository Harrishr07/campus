"""M05-12 integration tests: marking a period makes it Conducted and a Cancelled one cannot be marked, a state change
after marking needs a reason and is logged, and after the correction cut-off a marked status changes only through an
Attendance Correction Request the HOD approves (with a Version kept).

Fixture: the faculty portal fixture (T07 timetable published from Monday 2026-11-16, faculty_1 teaches the period).
"""

from unittest import mock

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, now_datetime

from campus.campus_platform.api import latest_request
from campus.campus_platform.approvals import approve
from campus.faculty import attendance_corrections
from campus.tests import demo
from campus.tests.test_faculty_portal import COLLEAGUE, TEACHER, FacultyPortalFixture
from campus.tests.test_timetable import CSE

HOD = demo.email("hod_cse")


class TestSessionMarkingAndCorrections(FacultyPortalFixture):
	def setUp(self):
		super().setUp()
		self.own = self.period_of("faculty_1")
		self.students = frappe.get_all("Student", pluck="name", limit=3, order_by="name")
		self.enrol(self.own.student_group, self.students)
		course = frappe.db.get_value("Course Schedule", self.own.name, "course")
		frappe.db.set_value(
			"Course", course, "department", CSE
		)  # the HOD approving is the course department's
		attendance_corrections.seed_policy()

	def state(self):
		return frappe.db.get_value("Course Schedule", self.own.name, "oc_session_state")

	def after_cutoff(self):
		later = add_to_date(now_datetime(), hours=attendance_corrections.cutoff_hours() + 1)
		return mock.patch("campus.faculty.attendance_corrections.now_datetime", return_value=later)

	def request(self, user, student, status, reason="Marked by mistake"):
		return self.as_user(
			user, attendance_corrections.request_correction, self.own.name, student, status, reason
		)

	def approve(self, name):
		correction = frappe.get_doc("Attendance Correction Request", name)
		self.as_user(HOD, approve, latest_request(correction).name)
		correction.reload()
		return correction

	def marked_hours_ago(self, hours):
		"""Date the period's records back, as if it was first marked `hours` ago."""
		frappe.db.set_value(
			"Student Attendance",
			{"course_schedule": self.own.name},
			"creation",
			add_to_date(now_datetime(), hours=-hours),
			update_modified=False,
		)

	def record_of(self, student):
		return frappe.db.get_value(
			"Student Attendance", {"course_schedule": self.own.name, "student": student, "docstatus": 1}
		)

	def other_session(self):
		"""Another (unmarked) session of the period's group."""
		return frappe.get_all(
			"Course Schedule",
			{"student_group": self.own.student_group, "name": ["!=", self.own.name]},
			pluck="name",
			limit=1,
		)[0]

	def comments(self, session):
		return frappe.get_all(
			"Comment",
			{"reference_doctype": "Course Schedule", "reference_name": session, "comment_type": "Info"},
			pluck="content",
		)

	def test_marking_makes_the_session_conducted_and_a_cancelled_one_cannot_be_marked(self):
		frappe.db.set_value("Course Schedule", self.own.name, "oc_session_state", "Cancelled")
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be marked"):
			self.mark(TEACHER, self.own.name, [])
		frappe.db.set_value("Course Schedule", self.own.name, "oc_session_state", "Scheduled")
		self.mark(TEACHER, self.own.name, [])
		self.assertEqual(self.state(), "Conducted")

	def test_a_state_change_after_marking_needs_a_reason_and_is_logged(self):
		self.mark(TEACHER, self.own.name, [])
		session = frappe.get_doc("Course Schedule", self.own.name)
		session.oc_session_state = "Cancelled"
		with self.assertRaisesRegex(frappe.ValidationError, "give the reason"):
			session.save()
		session.reload()
		session.oc_session_state, session.oc_state_reason = "Cancelled", "College closed for the flood"
		session.save()
		comments = frappe.get_all(
			"Comment",
			{"reference_doctype": "Course Schedule", "reference_name": self.own.name, "comment_type": "Info"},
			pluck="content",
		)
		self.assertTrue(any("Conducted to Cancelled: College closed for the flood" in c for c in comments))

	def test_a_rescheduled_session_needs_another_session_of_its_group(self):
		session = frappe.get_doc("Course Schedule", self.own.name)
		session.oc_session_state, session.oc_rescheduled_to = "Rescheduled", self.own.name
		with self.assertRaisesRegex(frappe.ValidationError, "another session"):
			session.save()

	def test_after_the_cut_off_a_change_needs_the_hods_approval(self):
		self.mark(TEACHER, self.own.name, [])
		first = self.students[0]
		with self.after_cutoff():
			with self.assertRaisesRegex(frappe.ValidationError, "Attendance Correction Request"):
				self.mark(TEACHER, self.own.name, [first])
			self.mark(TEACHER, self.own.name, [])  # the same marks again change nothing and pass
		self.assertEqual(self.attendance(self.own.name)[first], "Present")
		with self.assertRaises(frappe.PermissionError):
			self.request(COLLEAGUE, first, "Absent")  # not their period
		name = self.request(TEACHER, first, "Absent")
		correction = frappe.get_doc("Attendance Correction Request", name)
		self.assertEqual(
			(correction.current_status, correction.department, correction.docstatus), ("Present", CSE, 0)
		)
		self.assertEqual(
			self.attendance(self.own.name)[first], "Present"
		)  # nothing changes before the approval
		marked = correction.attendance
		self.as_user(HOD, approve, latest_request(correction).name)
		correction.reload()
		self.assertEqual(correction.docstatus, 1)
		self.assertEqual(self.attendance(self.own.name)[first], "Absent")
		self.assertEqual(frappe.db.get_value("Student Attendance", marked, "docstatus"), 2)
		version = frappe.get_doc("Version", correction.version)
		self.assertEqual(
			(version.ref_doctype, version.docname), ("Student Attendance", correction.corrected_attendance)
		)
		self.assertIn(["status", "Present", "Absent"], frappe.parse_json(version.data)["changed"])

	def test_a_correction_is_refused_without_an_approval_policy(self):
		self.mark(TEACHER, self.own.name, [])
		policies = frappe.get_all(
			"Approval Policy", {"document_type": attendance_corrections.DOCTYPE}, pluck="name"
		)
		frappe.db.set_value(
			"Approval Policy", {"name": ["in", policies]}, "document_type", "Approval Test Document"
		)
		self.addCleanup(
			frappe.db.set_value,
			"Approval Policy",
			{"name": ["in", policies]},
			"document_type",
			attendance_corrections.DOCTYPE,
		)
		with self.assertRaisesRegex(frappe.ValidationError, "No Approval Policy"):
			self.request(TEACHER, self.students[0], "Absent")
		self.assertEqual(self.attendance(self.own.name)[self.students[0]], "Present")

	def test_within_the_cut_off_the_teacher_re_marks_and_the_status_changes(self):
		first = self.students[0]
		self.mark(TEACHER, self.own.name, [first])
		self.assertEqual(self.attendance(self.own.name)[first], "Absent")
		self.marked_hours_ago(attendance_corrections.cutoff_hours() - 1)
		self.mark(TEACHER, self.own.name, [])
		self.assertEqual(self.attendance(self.own.name)[first], "Present")

	def test_re_marking_does_not_extend_the_cut_off(self):
		first, second = self.students[:2]
		self.mark(TEACHER, self.own.name, [])
		self.marked_hours_ago(40)
		self.mark(TEACHER, self.own.name, [first])  # hour 40: allowed, and writes a fresh record
		later = add_to_date(
			now_datetime(), hours=9
		)  # hour 49 since the first marking, hour 9 since the re-mark
		with mock.patch("campus.faculty.attendance_corrections.now_datetime", return_value=later):
			with self.assertRaisesRegex(frappe.ValidationError, "Attendance Correction Request"):
				self.mark(TEACHER, self.own.name, [first, second])
		self.assertEqual(self.attendance(self.own.name)[second], "Present")

	def test_after_the_cut_off_desk_cancel_amend_and_new_records_are_refused(self):
		first, second = self.students[:2]
		self.mark(TEACHER, self.own.name, [])
		marked = frappe.get_doc("Student Attendance", self.record_of(first))
		marked.cancel()  # within the cut-off the desk may cancel (and amend)
		amended = frappe.copy_doc(marked)
		amended.amended_from, amended.status, amended.docstatus = marked.name, "Absent", 0
		with self.after_cutoff():
			with self.assertRaisesRegex(frappe.ValidationError, "approved Attendance Correction Request"):
				amended.insert()
			with self.assertRaisesRegex(frappe.ValidationError, "approved Attendance Correction Request"):
				frappe.get_doc("Student Attendance", self.record_of(second)).cancel()
			fresh = frappe.copy_doc(marked)  # what Education's attendance tool writes
			fresh.status, fresh.docstatus = "Absent", 0
			with self.assertRaisesRegex(frappe.ValidationError, "approved Attendance Correction Request"):
				fresh.insert()
		self.assertEqual(self.attendance(self.own.name).get(second), "Present")
		self.assertNotIn(first, self.attendance(self.own.name))

	def test_after_the_cut_off_a_record_of_the_students_approved_leave_is_written(self):
		self.mark(TEACHER, self.own.name, [])
		first = self.students[0]
		frappe.get_doc("Student Attendance", self.record_of(first)).cancel()
		leave, date = self.leave_of(first)
		record = {
			"doctype": "Student Attendance",
			"student": first,
			"course_schedule": self.own.name,
			"date": date,
			"status": "Leave",
		}
		with self.after_cutoff():
			attendance_corrections.guard_record(
				frappe.get_doc({**record, "leave_application": leave})
			)  # as Education's leave approval writes it
			other = frappe.get_doc({**record, "student": self.students[1], "leave_application": leave})
			with self.assertRaisesRegex(frappe.ValidationError, "approved Attendance Correction Request"):
				attendance_corrections.guard_record(other)  # another student's leave does not back it

	def leave_of(self, student, docstatus=1, **extra):
		date = frappe.db.get_value("Course Schedule", self.own.name, "schedule_date")
		leave = frappe.get_doc(
			{
				"doctype": "Student Leave Application",
				"student": student,
				"from_date": date,
				"to_date": date,
				**extra,
			}
		)
		leave.flags.ignore_validate = True
		leave.insert(ignore_permissions=True)
		frappe.db.set_value("Student Leave Application", leave.name, "docstatus", docstatus)
		return leave.name, date

	def leave_record(self, student, leave, date, status="Leave"):
		return frappe.get_doc(
			{
				"doctype": "Student Attendance",
				"student": student,
				"course_schedule": self.own.name,
				"date": date,
				"status": status,
				"leave_application": leave,
			}
		)

	def test_a_draft_or_cancelled_leave_or_a_wrong_status_does_not_back_a_late_record(self):
		self.mark(TEACHER, self.own.name, [])
		first = self.students[0]
		frappe.get_doc("Student Attendance", self.record_of(first)).cancel()
		with self.after_cutoff():
			for docstatus in (0, 2):
				leave, date = self.leave_of(first, docstatus)
				with self.assertRaisesRegex(frappe.ValidationError, "approved Attendance Correction Request"):
					attendance_corrections.guard_record(self.leave_record(first, leave, date))
			leave, date = self.leave_of(first)
			with self.assertRaisesRegex(frappe.ValidationError, "approved Attendance Correction Request"):
				attendance_corrections.guard_record(self.leave_record(first, leave, date, "Present"))
			attendance_corrections.guard_record(self.leave_record(first, leave, date))
			frappe.db.set_value("Student Leave Application", leave, "mark_as_present", 1)
			attendance_corrections.guard_record(self.leave_record(first, leave, date, "Present"))
			with self.assertRaisesRegex(frappe.ValidationError, "approved Attendance Correction Request"):
				attendance_corrections.guard_record(self.leave_record(first, leave, date))

	def test_a_leave_link_does_not_let_a_late_cancel_through(self):
		self.mark(TEACHER, self.own.name, [])
		first = self.students[0]
		leave, date = self.leave_of(first)
		marked = frappe.get_doc("Student Attendance", self.record_of(first))
		frappe.db.set_value(
			"Student Attendance", marked.name, {"leave_application": leave, "status": "Leave"}
		)
		with self.after_cutoff():
			with self.assertRaisesRegex(frappe.ValidationError, "approved Attendance Correction Request"):
				frappe.get_doc("Student Attendance", marked.name).cancel()

	def test_a_record_without_a_session_has_the_cut_off_of_its_date(self):
		date = frappe.db.get_value("Course Schedule", self.own.name, "schedule_date")
		record = {
			"doctype": "Student Attendance",
			"student": self.students[0],
			"student_group": self.own.student_group,
			"date": date,
			"status": "Present",
		}
		hours = attendance_corrections.cutoff_hours()
		day_end = add_days(date, 1)

		def at(offset):
			return mock.patch(
				"campus.faculty.attendance_corrections.now_datetime",
				return_value=add_to_date(get_datetime(day_end), hours=offset),
			)

		with at(hours - 1):
			attendance_corrections.guard_record(frappe.get_doc(record))
		with at(hours + 1):
			with self.assertRaisesRegex(frappe.ValidationError, "approved Attendance Correction Request"):
				attendance_corrections.guard_record(frappe.get_doc(record))
			late = frappe.get_doc(record)
			late.flags.attendance_correction = True
			attendance_corrections.guard_record(late)

	def test_after_the_cut_off_a_never_marked_student_is_marked_through_a_request(self):
		self.mark(TEACHER, self.own.name, [])
		late = frappe.get_all(
			"Student", {"name": ["not in", self.students]}, pluck="name", limit=1, order_by="name"
		)[0]
		self.enrol(self.own.student_group, [late])
		with self.after_cutoff():
			with self.assertRaisesRegex(frappe.ValidationError, late):
				self.mark(TEACHER, self.own.name, [])
			correction = self.approve(self.request(TEACHER, late, "Leave"))
		self.assertEqual(correction.docstatus, 1)
		self.assertFalse(correction.current_status or correction.version)
		self.assertEqual(self.attendance(self.own.name)[late], "Leave")

	def test_an_approved_correction_is_refused_once_the_session_is_cancelled(self):
		self.mark(TEACHER, self.own.name, [])
		with self.after_cutoff():
			name = self.request(TEACHER, self.students[0], "Absent")
		frappe.db.set_value("Course Schedule", self.own.name, "oc_session_state", "Cancelled")
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be marked"):
			self.approve(name)
		self.assertEqual(self.attendance(self.own.name)[self.students[0]], "Present")

	def test_a_desk_request_is_only_for_the_requesters_own_period(self):
		request = frappe._dict(course_schedule=self.own.name)
		self.as_user(TEACHER, attendance_corrections.check_requester, request)  # their own period
		with self.assertRaises(frappe.PermissionError):
			self.as_user(COLLEAGUE, attendance_corrections.check_requester, request)
		attendance_corrections.check_requester(request)  # the academic office (System Manager) may raise any

	def test_a_makeup_for_a_marked_session_needs_a_reason_and_is_logged_on_both(self):
		self.mark(TEACHER, self.own.name, [])
		makeup = frappe.get_doc("Course Schedule", self.other_session())
		makeup.oc_session_state, makeup.oc_makeup_for = "Makeup", self.own.name
		with self.assertRaisesRegex(frappe.ValidationError, "give the reason"):
			makeup.save()
		makeup.reload()
		makeup.oc_session_state, makeup.oc_makeup_for, makeup.oc_state_reason = (
			"Makeup",
			self.own.name,
			"Projector failed",
		)
		makeup.save()
		self.assertTrue(
			any(f"to Makeup for {self.own.name}: Projector failed" in c for c in self.comments(makeup.name))
		)
		self.assertTrue(
			any(
				f"{makeup.name} changed from" in c and "Projector failed" in c
				for c in self.comments(self.own.name)
			)
		)
		makeup.oc_makeup_for = self.own.name  # unchanged link, other edits: no new reason needed
		makeup.save()

	def test_re_pointing_a_makeup_away_from_a_marked_session_needs_a_reason(self):
		self.mark(TEACHER, self.own.name, [])
		other = self.other_session()
		frappe.db.set_value(
			"Course Schedule",
			other,
			{"oc_session_state": "Makeup", "oc_makeup_for": self.own.name, "oc_state_reason": "Old"},
		)
		makeup = frappe.get_doc("Course Schedule", other)
		makeup.oc_session_state, makeup.oc_makeup_for = "Scheduled", None
		with self.assertRaisesRegex(frappe.ValidationError, "give the reason"):
			makeup.save()

	def test_a_session_has_at_most_one_makeup(self):
		sessions = frappe.get_all(
			"Course Schedule",
			{"student_group": self.own.student_group, "name": ["!=", self.own.name]},
			pluck="name",
			limit=2,
		)
		frappe.db.set_value(
			"Course Schedule", sessions[0], {"oc_session_state": "Makeup", "oc_makeup_for": self.own.name}
		)
		second = frappe.get_doc("Course Schedule", sessions[1])
		second.oc_session_state, second.oc_makeup_for = "Makeup", self.own.name
		with self.assertRaisesRegex(frappe.ValidationError, "already has a Makeup"):
			second.save()
