"""PR-02 least privilege for the pilot teacher logins: faculty, HOD, class advisor and COE no longer hold the office role
(Academics User), a re-run of the kit takes it away from existing pilot users, and each role's UAT path still works
under the reduced roles. The demo teachers of campus.tests.demo hold Academics User; each test here takes it away.

COE: its flows (exam registrations, hall tickets, results, grade sheets) are proven with a COE-only login in
test_exam_registration, test_hall_tickets and test_results; this module checks its desk areas and reports.
"""

import json
from unittest import mock

import frappe
from frappe.boot import get_bootinfo
from frappe.desk.query_report import get_report_doc
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_to_date, now_datetime, today

from campus.campus_platform.api import latest_request
from campus.campus_platform.approvals import approve, request_approval
from campus.faculty import attendance_corrections, portal, portal_mentoring
from campus.setup import people
from campus.setup.demo_data import staff
from campus.setup.profile import PROFILE_DIR
from campus.student_services import corrections
from campus.tests import demo
from campus.tests.test_faculty_portal import COLLEAGUE, TEACHER, FacultyPortalFixture
from campus.tests.test_mentoring import MENTOR_A, MentoringFixture
from campus.tests.test_timetable import CSE, employee

OFFICE_ROLE = "Academics User"
SXCCE = json.loads((PROFILE_DIR / "sxcce.json").read_text())
KIT_ROLES = {user["key"]: user["roles"] for user in SXCCE["users"]}
TEACHING_KEYS = ("faculty", "hod", "class_advisor", "coe")
HOD = demo.email("hod_cse")
CORRECTION = "Attendance Correction Request"
BY_HAND = "Report Manager"  # a role the kit never gives
# The desk areas each pilot role's guide (docs/usage/roles) names, and office areas it must not see.
AREAS = {
	"faculty": ({"Academics", "Examinations", "Student Services", "Faculty", "Approvals"}, {"Communication", "Academic Governance"}),
	"hod": ({"Academic Governance", "Academics", "Communication", "Examinations", "Faculty", "Student Services", "Approvals"}, set()),
	"class_advisor": ({"Student Services", "Approvals"}, {"Communication", "Academic Governance"}),
	"coe": ({"Examinations", "Academics", "Student Services", "Approvals"}, {"Communication", "Academic Governance", "Faculty"}),
}
REPORTS = {
	"faculty": ("My Pending Approvals",),
	"hod": ("My Pending Approvals", "Workload Balance", "Timetable Clash Checker", "Attendance Shortage", "CIA Status by Offering"),
	"class_advisor": ("My Pending Approvals", "Attendance Shortage"),
	"coe": ("My Pending Approvals", "Exam Eligibility Withheld", "CIA Status by Offering", "Result Analysis", "Rank List", "Arrear List"),
}


def as_user(user, fn, *args, **kwargs):
	frappe.set_user(user)
	try:
		return fn(*args, **kwargs)
	finally:
		frappe.set_user("Administrator")


def drop_office_role(case, *users):
	"""Take Academics User from demo teachers for one test (the fixtures' savepoint rollback gives it back)."""
	for user in users:
		frappe.db.delete("Has Role", {"parent": user, "parenttype": "User", "role": OFFICE_ROLE})
		frappe.clear_cache(user=user)
		case.addCleanup(restore_office_role, user)


def restore_office_role(user):
	if not frappe.db.exists("Has Role", {"parent": user, "parenttype": "User", "role": OFFICE_ROLE}):
		frappe.get_doc({"doctype": "Has Role", "parent": user, "parenttype": "User", "parentfield": "roles", "role": OFFICE_ROLE}).db_insert()
	frappe.clear_cache(user=user)


def kit_login(key):
	"""A login holding exactly the pilot kit's role set of `key`."""
	email = f"campus-pilot-roles-{key.replace('_', '-')}@example.com"
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": key, "send_welcome_email": 0, "roles": [{"role": r} for r in KIT_ROLES[key]]}
		).insert()  # fmt: skip
	return email


class TestKitRoleSets(IntegrationTestCase):
	def test_teachers_hold_no_office_role_and_the_office_keeps_it(self):
		for key in TEACHING_KEYS:
			self.assertNotIn(OFFICE_ROLE, KIT_ROLES[key], key)
		self.assertEqual(KIT_ROLES["office"], [OFFICE_ROLE])
		self.assertEqual((staff.HOD_ROLES, staff.FACULTY_ROLES), (["HOD", "Instructor"], ["Instructor"]))
		self.assertEqual(set(KIT_ROLES["class_advisor"]), {"Class Advisor", "Mentor", "Instructor"})
		self.assertEqual(KIT_ROLES["coe"], ["COE"])

	def test_a_sync_takes_away_only_the_kit_roles_the_spec_no_longer_lists(self):
		user = "campus-pilot-roles-sync@example.com"
		frappe.get_doc(
			{"doctype": "User", "email": user, "first_name": "sync", "send_welcome_email": 0,
			"roles": [{"role": r} for r in ("Instructor", OFFICE_ROLE, BY_HAND)]}
		).insert()  # fmt: skip
		managed = people.kit_roles(SXCCE)
		self.assertIn(OFFICE_ROLE, managed)
		self.assertNotIn(BY_HAND, managed)
		self.assertEqual(people.sync_roles(user, ["Instructor", "Mentor"], managed), [OFFICE_ROLE])
		held = set(frappe.get_roles(user))
		self.assertTrue({"Instructor", "Mentor", BY_HAND} <= held)  # a role outside the kit's set is left alone
		self.assertNotIn(OFFICE_ROLE, held)
		self.assertEqual(people.sync_roles(user, ["Instructor", "Mentor"], managed), [])  # idempotent
		self.assertEqual(set(frappe.get_roles(user)), held)

	def test_a_sync_keeps_a_kit_role_an_active_position_gives(self):
		user = "campus-pilot-roles-position@example.com"
		frappe.get_doc(
			{"doctype": "User", "email": user, "first_name": "position", "send_welcome_email": 0, "roles": [{"role": r} for r in ("Instructor", "Mentor")]}
		).insert()  # fmt: skip
		mentor_seat = [frappe._dict(name="seat", position="MENTOR", role="Mentor", role_granted=1)]
		with mock.patch("campus.setup.people.active_holdings", return_value=mentor_seat):
			self.assertEqual(people.sync_roles(user, ["Instructor"], people.kit_roles(SXCCE)), [])
		self.assertIn("Mentor", frappe.get_roles(user))
		self.assertEqual(people.sync_roles(user, ["Instructor"], people.kit_roles(SXCCE)), ["Mentor"])  # the seat ended

	@mock.patch("campus.campus_platform.pack_visibility.hidden_workspaces", return_value=set())
	def test_each_role_sees_its_desk_areas_and_no_office_area(self, _packs):
		for key, (wanted, refused) in AREAS.items():
			user = kit_login(key)
			frappe.set_user(user)
			try:  # module packs are per college (test_navigation); here only the roles decide
				frappe.cache.hdel("desktop_icons", user)
				frappe.cache.hdel("bootinfo", user)
				areas = {i["label"] for i in get_bootinfo().desktop_icons if i.get("app") == "campus"}
			finally:
				frappe.set_user("Administrator")
			self.assertTrue(wanted <= areas, f"{key}: missing {wanted - areas}")
			self.assertTrue(refused.isdisjoint(areas), f"{key}: sees {refused & areas}")
			self.assertTrue({"Fees and Finance", "Admissions"}.isdisjoint(areas), key)

	def test_each_role_opens_the_reports_of_its_uat_script(self):
		for key, reports in REPORTS.items():
			user = kit_login(key)
			for report in reports:
				self.assertEqual(as_user(user, get_report_doc, report).name, report, f"{key}: {report}")

	def test_no_teacher_creates_a_student_or_a_record_correction(self):
		for key in TEACHING_KEYS:
			user = kit_login(key)
			for doctype in ("Student", "Student Record Correction", "Student Applicant"):
				self.assertFalse(frappe.has_permission(doctype, "create", user=user), f"{key}: {doctype}")


class TestFacultyAndHodWithoutTheOfficeRole(FacultyPortalFixture):
	def setUp(self):
		super().setUp()
		drop_office_role(self, TEACHER, COLLEAGUE, HOD)
		self.own = self.period_of("faculty_1")
		self.others = self.period_of("faculty_2")
		# the teacher's own college: the desk form checks the teacher's company User Permission on the student
		self.students = frappe.get_all("Student", {"oc_company": demo.ENGINEERING}, pluck="name", limit=3, order_by="name")
		for period in (self.own, self.others):
			self.enrol(period.student_group, self.students)
		course = frappe.db.get_value("Course Schedule", self.own.name, "course")
		frappe.db.set_value("Course", course, "department", CSE)  # the HOD approving is the course department's
		attendance_corrections.seed_policy()

	def after_cutoff(self):
		later = add_to_date(now_datetime(), hours=attendance_corrections.cutoff_hours() + 1)
		return mock.patch("campus.faculty.attendance_corrections.now_datetime", return_value=later)

	def raise_at_desk(self, user, schedule, student, status="Absent"):
		"""The Faculty > Attendance Correction Request form: insert with the user's own rights, then Request Approval."""

		def raise_request():
			doc = frappe.get_doc({"doctype": CORRECTION, "course_schedule": schedule, "student": student, "new_status": status, "reason": "Marked by mistake"})
			doc.insert()
			request_approval(CORRECTION, doc.name)
			return doc.name

		return as_user(user, raise_request)

	def test_the_demo_teachers_hold_the_kit_role_sets(self):
		self.assertTrue(set(KIT_ROLES["faculty"]) <= set(frappe.get_roles(TEACHER)))
		self.assertTrue(set(KIT_ROLES["hod"]) <= set(frappe.get_roles(HOD)))
		for user in (TEACHER, COLLEAGUE, HOD):
			self.assertNotIn(OFFICE_ROLE, frappe.get_roles(user), user)

	def test_the_teacher_marks_attendance_of_own_period_only(self):
		self.assertEqual(self.mark(TEACHER, self.own.name, [self.students[1]]), {"present": 2, "absent": 1})
		self.assertEqual(self.attendance(self.own.name)[self.students[1]], "Absent")
		with self.assertRaises(frappe.PermissionError):
			self.mark(TEACHER, self.others.name, [])
		self.assertEqual(self.attendance(self.others.name), {})

	def test_the_teacher_raises_a_correction_at_the_desk_and_the_hod_approves_it(self):
		self.mark(TEACHER, self.own.name, [])
		first = self.students[0]
		self.assertTrue(frappe.has_permission("Course Schedule", "select", user=TEACHER))  # the form's period link
		with self.after_cutoff():
			name = self.raise_at_desk(TEACHER, self.own.name, first)
		correction = frappe.get_doc(CORRECTION, name)
		self.assertEqual((correction.owner, correction.department, correction.docstatus), (TEACHER, CSE, 0))
		with self.assertRaises(frappe.PermissionError):
			as_user(TEACHER, approve, latest_request(correction).name)  # the requester cannot approve it
		self.assertFalse(frappe.has_permission(CORRECTION, "read", correction, user=COLLEAGUE))  # own requests only
		self.assertTrue(frappe.has_permission(CORRECTION, "read", correction, user=HOD))
		as_user(HOD, approve, latest_request(correction).name)
		correction.reload()
		self.assertEqual(correction.docstatus, 1)
		self.assertEqual(self.attendance(self.own.name)[first], "Absent")

	def test_a_teacher_cannot_raise_a_correction_for_another_teachers_period(self):
		self.mark(TEACHER, self.own.name, [])
		with self.after_cutoff(), self.assertRaises(frappe.PermissionError):
			self.raise_at_desk(COLLEAGUE, self.own.name, self.students[0])
		self.assertFalse(frappe.db.exists(CORRECTION, {"course_schedule": self.own.name}))

	def test_a_teacher_cannot_create_a_student_or_a_record_correction(self):
		student = {"doctype": "Student", "first_name": "Pilot", "last_name": "Intruder", "student_email_id": "campus-pilot-intruder@example.com"}
		with self.assertRaises(frappe.PermissionError):
			as_user(TEACHER, lambda: frappe.get_doc(student).insert())
		correction = {"doctype": "Student Record Correction", "student": self.students[0], "category": "Personal", "reason": "x"}
		with self.assertRaises(frappe.PermissionError):
			as_user(TEACHER, lambda: frappe.get_doc(correction).insert())
		with self.assertRaises(frappe.PermissionError):
			as_user(TEACHER, corrections.raise_correction, "Contact", "student_mobile_number", "9876543210", "x", student=self.students[0])
		self.assertFalse(frappe.db.exists("Student", {"student_email_id": student["student_email_id"]}))

	def test_the_teacher_sees_own_mentees_in_the_portal(self):
		frappe.db.set_value("Student", self.students[0], "oc_mentor", employee("faculty_1"))
		self.assertEqual([m["student"] for m in as_user(TEACHER, portal.my_mentees)], [self.students[0]])

	def test_the_hod_writes_and_submits_a_circular_to_the_department(self):
		rule = frappe.get_doc(
			{"doctype": "Audience Rule", "rule_name": "Pilot roles CSE staff", "company": demo.ENGINEERING, "rule_type": "Department", "department": CSE}
		).insert().name  # fmt: skip

		def circulate():
			doc = frappe.get_doc(
				{"doctype": "Circular", "title": "Department meeting", "company": demo.ENGINEERING, "audience_rule": rule,
				"publish_from": now_datetime(), "body": "Friday 3 pm"}
			).insert()  # fmt: skip
			doc.submit()
			return doc.name

		self.assertTrue(frappe.has_permission("Audience Rule", "read", rule, user=HOD))
		self.assertEqual(frappe.db.get_value("Circular", as_user(HOD, circulate), "docstatus"), 1)
		with self.assertRaises(frappe.PermissionError):
			as_user(TEACHER, circulate)


class TestClassAdvisorWithoutTheOfficeRole(MentoringFixture):
	def setUp(self):
		super().setUp()
		drop_office_role(self, MENTOR_A)
		frappe.get_doc("User", MENTOR_A).add_roles("Class Advisor")
		frappe.clear_cache(user=MENTOR_A)

	def test_the_advisor_holds_the_kit_role_set(self):
		held = set(frappe.get_roles(MENTOR_A))
		self.assertTrue(set(KIT_ROLES["class_advisor"]) <= held)
		self.assertNotIn(OFFICE_ROLE, held)

	def test_the_advisor_adds_a_mentoring_note_and_lists_the_mentees(self):
		mentees = [m["student"] for m in as_user(MENTOR_A, portal.my_mentees)]
		self.assertIn(self.a_student, mentees)
		self.assertNotIn(self.b_student, mentees)
		note = as_user(MENTOR_A, portal_mentoring.add_note, self.a_student, "Personal", "Settling in", follow_up_date=add_days(today(), 7))
		self.assertEqual([n["name"] for n in as_user(MENTOR_A, portal_mentoring.mentee_record, self.a_student)["notes"]], [note])
		with self.assertRaises(frappe.PermissionError):
			as_user(MENTOR_A, portal_mentoring.mentee_record, self.b_student)

	def test_the_advisor_reads_leave_and_condonation_but_creates_no_student(self):
		for doctype in ("Student Leave Application", "Condonation Request", "Parent Interaction"):
			self.assertTrue(frappe.has_permission(doctype, "read", user=MENTOR_A), doctype)
		self.assertEqual(as_user(MENTOR_A, get_report_doc, "Attendance Shortage").name, "Attendance Shortage")
		for doctype in ("Student", "Student Record Correction", "Condonation Request"):
			self.assertFalse(frappe.has_permission(doctype, "create", user=MENTOR_A), doctype)
