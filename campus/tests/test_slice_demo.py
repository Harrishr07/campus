"""S5 end-to-end test: make_demo("slice") builds the whole pilot path and every step has its expected outcome."""

import json
from unittest.mock import patch

import frappe

from campus.admissions.api import admit
from campus.admissions.report.live_seat_matrix import live_seat_matrix
from campus.examinations.report.result_analysis.result_analysis import execute as result_analysis
from campus.iqac.registry import data_point
from campus.iqac.setup import FRAMEWORK
from campus.student_services import portal
from campus.student_services.api import attendance_summary, student_offerings
from campus.tests import demo, demo_slice
from campus.tests.demo_slice import APPLICANTS, COURSES
from campus.tests.utils import CampusTestCase

COUNTED = [
	"Student", "Student Applicant", "Program Enrollment", "Sales Invoice", "Payment Entry", "Course Registration",
	"Student Group", "Course Schedule", "Student Attendance", "Mark Sheet Entry", "Student Result", "Exam Session",
	"Verifiable Document", "Accreditation Cycle", "Metric Value", "Fee Structure", "Curriculum", "User", "Guardian",
]  # fmt: skip


class TestSliceDemo(CampusTestCase):
	demo_scale = "slice"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.students = demo_slice.slice_students()
		cls.session = frappe.db.get_value("Exam Session", {"company": demo.ENGINEERING})

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")

	def result(self, number):
		return frappe.get_doc("Student Result", f"SR-{self.session}-{self.students[number]}")

	def grades(self, number):
		return {row.course: (row.grade, row.result) for row in self.result(number).courses}

	def course(self, index):
		return frappe.db.get_value("Course", {"course_name": COURSES[index][0]})

	def test_five_applicants_admitted_one_under_management_quota(self):
		self.assertEqual(len(APPLICANTS), 5)
		self.assertTrue(all(self.students))
		statuses = frappe.get_all(
			"Student Applicant", {"student_email_id": ["like", "slice-%"]}, ["student_email_id", "application_status"], order_by="student_email_id"
		)
		self.assertEqual([s.application_status for s in statuses], ["Admitted"] * 5 + ["Approved"])  # slice-6 is left for the live demo
		enrollments = frappe.get_all(
			"Program Enrollment", {"student": ["in", self.students], "docstatus": 1}, ["student", "oc_admission_quota"]
		)
		self.assertEqual(sorted(e.oc_admission_quota for e in enrollments), ["GQ"] * 4 + ["MQ"])
		self.assertRegex(frappe.db.get_value("Student", self.students[0], "oc_register_no"), r"^DCE26CSE\d{4}$")
		self.assertTrue(all(frappe.db.get_value("Student", s, "oc_regulation") for s in self.students))

	def test_the_admission_officer_can_admit_the_sixth_applicant_live(self):
		applicant = frappe.db.get_value("Student Applicant", {"student_email_id": demo.email(demo_slice.LIVE_APPLICANT[0])})
		frappe.db.savepoint("live_admit")
		self.addCleanup(frappe.db.rollback, save_point="live_admit")
		frappe.set_user(demo.email("admissions"))
		admitted = admit(applicant)
		self.assertEqual(frappe.db.get_value("Student Applicant", applicant, "application_status"), "Admitted")
		self.assertEqual(frappe.db.get_value("Sales Invoice", admitted["invoice"], "grand_total"), 65000)

	def test_fees_invoiced_for_all_and_four_paid(self):
		invoices = frappe.get_all(
			"Sales Invoice", {"student": ["in", self.students], "docstatus": 1}, ["student", "grand_total", "outstanding_amount"]
		)
		self.assertEqual(len(invoices), 5)
		due = [i for i in invoices if i.outstanding_amount]
		self.assertEqual([(d.student, d.grand_total) for d in due], [(self.students[4], 155000)])  # management quota fee
		self.assertEqual(sorted(i.grand_total for i in invoices if not i.outstanding_amount), [65000] * 4)

	def test_registration_enrols_every_student_in_the_four_offerings(self):
		registrations = frappe.get_all(
			"Course Registration", {"student": ["in", self.students], "docstatus": 1}, pluck="student"
		)
		self.assertEqual(sorted(registrations), sorted(self.students))
		curriculum = frappe.get_doc("Curriculum", {"program": demo_slice.PROGRAM, "status": "Effective"})
		self.assertEqual((curriculum.total_credits, len(curriculum.courses)), (14, 4))
		for student in self.students:
			self.assertEqual(len(student_offerings(student, demo_slice.academic_term())), 4)

	def test_attendance_bands_follow_the_r2026_rule(self):
		term = demo_slice.academic_term()
		statuses = [attendance_summary(s, term)["status"] for s in self.students]
		self.assertEqual(statuses, ["Eligible", "Eligible", "Shortage", "Medical band", "Eligible"])
		summary = attendance_summary(self.students[2], term)
		self.assertEqual(summary["overall_pct"], 58.33)  # 14 of 24 in every course
		self.assertEqual(summary["offerings"][0]["conducted"], demo_slice.SESSIONS)

	def test_results_carry_the_su_codes_and_hand_computed_sgpa(self):
		self.assertEqual({r[0] for r in self.grades(2).values()}, {"SA"})  # attendance shortage: every course SA
		self.assertEqual(self.grades(4)[self.course(0)], ("AB", "AB"))  # absent in Matrices and Calculus
		self.assertEqual(self.grades(1)[self.course(0)], ("U", "Fail"))  # ESE 24/60 = 40% is below 45%
		self.assertEqual(self.grades(0), {
			self.course(0): ("A+", "Pass"), self.course(1): ("S", "Pass"), self.course(2): ("A", "Pass"), self.course(3): ("A+", "Pass"),
		})  # fmt: skip
		# SGPA = sum(credits x grade point) / sum(credits) over passed courses; credits 4, 4, 4, 2
		self.assertEqual(self.result(0).sgpa, 9.0)  # (4x9 + 4x10 + 4x8 + 2x9) / 14
		self.assertEqual(self.result(3).sgpa, 6.86)  # (4x7 + 4x7 + 4x6.5 + 2x7) / 14 = 96 / 14
		self.assertEqual(self.result(1).sgpa, 7.6)  # (4x8 + 4x7 + 2x8) / 10: the failed course is left out
		self.assertEqual(self.result(0).cgpa, 9.0)

	def test_session_is_published_in_the_past_as_the_final_year_session(self):
		session = frappe.get_doc("Exam Session", self.session)
		self.assertEqual((session.status, session.is_final_year), ("Published", 1))
		self.assertLess(session.publish_at, frappe.utils.now_datetime())
		self.assertEqual(frappe.db.count("Student Result", {"exam_session": self.session}), 5)

	def test_one_grade_sheet_is_issued_with_a_qr_code(self):
		documents = frappe.get_all(
			"Verifiable Document", {"reference_doctype": "Student Result"}, ["reference_name", "document_type", "status"]
		)
		self.assertEqual([(d.reference_name, d.status) for d in documents], [(self.result(0).name, "Valid")])

	def test_aqar_cycle_has_the_hand_counted_final_year_pass_percentage(self):
		cycle = frappe.get_doc("Accreditation Cycle", {"framework": FRAMEWORK, "academic_year": demo_slice.YEAR})
		metric = frappe.get_doc("Metric Value", f"{cycle.name}-2.6.3")  # the college row; department rows have their own names
		# appeared: students 1, 2, 4, 5 (student 3 is all SA); passed: 1 and 4 (2 failed a course, 5 was absent in one)
		self.assertEqual(metric.value, 50)
		inputs = json.loads(metric.snapshot)["inputs"]
		self.assertEqual(
			[r["name"] for r in inputs["final_year_passed"]["records"]], sorted(self.result(n).name for n in (0, 3))
		)
		self.assertEqual(inputs["final_year_appeared"]["value"], 4)
		admitted = frappe.get_doc("Metric Value", f"{cycle.name}-2.1.1")
		self.assertEqual(
			admitted.value,
			frappe.db.count("Program Enrollment", {"oc_company": demo.ENGINEERING, "academic_year": demo_slice.YEAR, "docstatus": 1}),
		)

	def test_coe_data_points_match_the_result_analysis_of_the_demo(self):
		# appeared: students 1, 2, 4, 5 (student 3 is all SA); passed every course: 1 and 4 (P2-T24)
		filters = {"company": demo.ENGINEERING, "academic_year": demo_slice.YEAR, "group_by": "Program", "final_year_only": 1}
		total = result_analysis(filters)[1][-1]
		self.assertEqual((total["appeared"], total["passed"], total["pass_pct"]), (4, 2, 50))
		self.assertEqual(data_point("pass_percentage", demo.ENGINEERING, demo_slice.YEAR)["value"], total["pass_pct"])
		self.assertEqual(data_point("students_appeared", demo.ENGINEERING, demo_slice.YEAR)["value"], total["appeared"])

	def test_reserved_seat_data_points_are_filled_from_the_flagged_demo_categories(self):
		filled = data_point("reserved_seats_filled", demo.ENGINEERING, demo_slice.YEAR)
		earmarked = data_point("seats_earmarked_reserved", demo.ENGINEERING, demo_slice.YEAR)
		self.assertEqual(filled["value"], 3)  # the BC, MBC and SC government-quota students; OC is open
		self.assertEqual(earmarked["value"], 50)  # 10 seats each: government BC, MBC, SC, ST and management BC
		report = live_seat_matrix.data(frappe._dict(company=demo.ENGINEERING, program=demo_slice.PROGRAM, academic_year=demo_slice.YEAR))
		reserved = [r for r in report if r["category"] in demo.RESERVED_CATEGORIES and not r["supernumerary"]]
		self.assertEqual((filled["value"], earmarked["value"]), (sum(r["filled"] for r in reserved), sum(r["sanctioned"] for r in reserved)))

	def test_portal_shows_student_1_only_their_own_data(self):
		frappe.set_user(demo.email("student_1"))
		own, other = self.students[0], self.students[1]
		self.assertEqual([s.name for s in portal.my_students()], [own])
		fees = portal.get_fees()
		self.assertEqual((fees.student, len(fees.invoices), fees.total_outstanding), (own, 1, 0))
		self.assertEqual(portal.get_attendance()["summary"]["status"], "Eligible")
		results = portal.get_results()["results"]
		self.assertEqual([(r["sgpa"], len(r["courses"])) for r in results], [(9.0, 4)])
		for method in (portal.get_fees, portal.get_attendance, portal.get_results):
			with self.assertRaises(frappe.PermissionError):
				method(other)

	def test_guardian_1_sees_the_same_student_and_nobody_else(self):
		frappe.set_user(demo.email("guardian_1"))
		self.assertEqual([s.name for s in portal.my_students()], [self.students[0]])
		self.assertEqual(portal.get_results()["results"][0]["sgpa"], 9.0)
		with self.assertRaises(frappe.PermissionError):
			portal.get_fees(self.students[4])

	def test_logins_are_enabled_with_the_demo_password(self):
		from frappe.utils.password import check_password

		for username in demo.USERS:
			self.assertEqual(frappe.db.get_value("User", demo.email(username), "enabled"), 1)
		for username in ("student_1", "guardian_1", "faculty_1", "coe", "iqac"):
			self.assertEqual(check_password(demo.email(username), demo_slice.PASSWORD), demo.email(username))

	def test_make_demo_refuses_outside_a_demo_site(self):
		with patch.dict(frappe.local.conf, {"developer_mode": 0, "campus_demo_site": 0}):
			with self.assertRaisesRegex(frappe.ValidationError, "demo sites only"):
				demo.make_demo("slice")

	def test_existing_passwords_are_not_reset(self):
		from frappe.utils.password import check_password, update_password

		frappe.db.savepoint("password_test")
		self.addCleanup(frappe.db.rollback, save_point="password_test")
		user = demo.email("coe")
		update_password(user, "Changed#Pass2026")
		demo.make_demo("slice")
		self.assertEqual(check_password(user, "Changed#Pass2026"), user)

	def test_second_run_creates_nothing(self):
		before = {doctype: frappe.db.count(doctype) for doctype in COUNTED}
		demo.make_demo("slice")
		self.assertEqual({doctype: frappe.db.count(doctype) for doctype in COUNTED}, before)


class TestDeskButtons(CampusTestCase):
	def test_button_scripts_are_hooked_and_call_whitelisted_methods(self):
		import re

		from frappe import get_hooks

		hooked = get_hooks("doctype_js", app_name="campus")
		for doctype, script in (("Student Applicant", "student_applicant.js"), ("Student Result", "student_result.js")):
			self.assertIn(f"public/js/{script}", hooked[doctype])
			source = open(frappe.get_app_path("campus", "public", "js", script)).read()
			constants = dict(re.findall(r'const (\w+) = "([\w.]+)"', source))
			methods = {constants[c] for c in re.findall(r"method: (\w+)", source)}
			self.assertTrue(methods, script)
			for method in methods:
				self.assertIn(frappe.get_attr(method), frappe.whitelisted, method)
