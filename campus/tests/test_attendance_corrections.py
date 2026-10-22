"""M05-12 integration tests: marking a period makes it Conducted and a Cancelled one cannot be marked, a state change
after marking needs a reason and is logged, and after the correction cut-off a marked status changes only through an
Attendance Correction Request the HOD approves (with a Version kept).

Fixture: the faculty portal fixture (T07 timetable published from Monday 2026-11-16, faculty_1 teaches the period).
"""

from unittest import mock

import frappe
from frappe.utils import add_to_date, now_datetime

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
		frappe.db.set_value("Course", course, "department", CSE)  # the HOD approving is the course department's
		attendance_corrections.seed_policy()

	def state(self):
		return frappe.db.get_value("Course Schedule", self.own.name, "oc_session_state")

	def after_cutoff(self):
		later = add_to_date(now_datetime(), hours=attendance_corrections.cutoff_hours() + 1)
		return mock.patch("campus.faculty.attendance_corrections.now_datetime", return_value=later)

	def request(self, user, student, status, reason="Marked by mistake"):
		return self.as_user(user, attendance_corrections.request_correction, self.own.name, student, status, reason)

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
		comments = frappe.get_all("Comment", {"reference_doctype": "Course Schedule", "reference_name": self.own.name, "comment_type": "Info"}, pluck="content")
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
		self.assertEqual((correction.current_status, correction.department, correction.docstatus), ("Present", CSE, 0))
		self.assertEqual(self.attendance(self.own.name)[first], "Present")  # nothing changes before the approval
		marked = correction.attendance
		self.as_user(HOD, approve, latest_request(correction).name)
		correction.reload()
		self.assertEqual(correction.docstatus, 1)
		self.assertEqual(self.attendance(self.own.name)[first], "Absent")
		self.assertEqual(frappe.db.get_value("Student Attendance", marked, "docstatus"), 2)
		version = frappe.get_doc("Version", correction.version)
		self.assertEqual((version.ref_doctype, version.docname), ("Student Attendance", correction.corrected_attendance))
		self.assertIn(["status", "Present", "Absent"], frappe.parse_json(version.data)["changed"])

	def test_a_correction_is_refused_without_an_approval_policy(self):
		self.mark(TEACHER, self.own.name, [])
		policies = frappe.get_all("Approval Policy", {"document_type": attendance_corrections.DOCTYPE}, pluck="name")
		frappe.db.set_value("Approval Policy", {"name": ["in", policies]}, "document_type", "Approval Test Document")
		self.addCleanup(frappe.db.set_value, "Approval Policy", {"name": ["in", policies]}, "document_type", attendance_corrections.DOCTYPE)
		with self.assertRaisesRegex(frappe.ValidationError, "No Approval Policy"):
			self.request(TEACHER, self.students[0], "Absent")
		self.assertEqual(self.attendance(self.own.name)[self.students[0]], "Present")
