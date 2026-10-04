"""P1-T02 tests: the standard demo data builder is complete, correct and idempotent."""

import frappe

from campus.campus_platform.api import get_regulation, resolve_position
from campus.campus_platform.doctype.regulation.regulation import regulation_name
from campus.tests import demo
from campus.tests.utils import CampusTestCase

DEMO_DOCTYPES = ["Academic Year", "Academic Term", "Department", "Employee", "Instructor"]


def snapshot():
	counts = demo.counts()
	for doctype in [*DEMO_DOCTYPES, "Program Enrollment", "Position Holder", "Institution Profile",
			"Shared Service Agreement", "User Permission", "Student Category", "Guardian"]:
		counts[doctype] = frappe.db.count(doctype)
	return counts


class TestDemoData(CampusTestCase):
	demo_scale = "small"

	def test_second_run_creates_nothing(self):
		before = snapshot()
		demo.make_demo("small")
		self.assertEqual(snapshot(), before)

	def test_small_scale_counts(self):
		counts = demo.counts()
		self.assertEqual(counts["Company"], 3)
		self.assertEqual(counts["Program"], 4)
		self.assertEqual(counts["Regulation"], 4)
		self.assertEqual(counts["Student"], 30)  # 10 per engineering program, 2026-27 batch
		self.assertEqual(frappe.db.count("Institution Profile", {"name": ["in", demo.ALL_COMPANIES]}), 3)

	def test_company_hierarchy_and_profiles(self):
		self.assertTrue(frappe.db.get_value("Company", demo.TRUST, "is_group"))
		for college in (demo.ENGINEERING, demo.ARTS):
			self.assertEqual(frappe.db.get_value("Company", college, "parent_company"), demo.TRUST)
		profile = frappe.get_doc("Institution Profile", demo.ENGINEERING)
		self.assertEqual((profile.institution_status, str(profile.status_effective_from)), ("Autonomous", "2022-05-26"))
		self.assertEqual(frappe.db.get_value("Institution Profile", demo.ARTS, "institution_status"), "Affiliated")

	def test_students_resolve_to_effective_regulation_with_category_spread(self):
		students = frappe.get_all(
			"Student",
			filters={"student_email_id": ["like", f"%@{demo.DOMAIN}"]},
			fields=["name", "oc_regulation", "oc_batch", "oc_company"],
		)
		categories = frappe.get_all(
			"Program Enrollment", filters={"student": ["in", [s.name for s in students]]}, pluck="student_category"
		)
		self.assertEqual({s.oc_regulation for s in students}, {regulation_name("R2026", demo.ENGINEERING)})
		self.assertEqual({s.oc_batch for s in students}, {"2026-27"})
		self.assertEqual({s.oc_company for s in students}, {demo.ENGINEERING})
		self.assertEqual(set(categories), set(demo.CATEGORIES))
		self.assertEqual(get_regulation(students[0].name), regulation_name("R2026", demo.ENGINEERING))

	def test_regulations_cover_programs_per_batch(self):
		from campus.campus_platform.regulation_rules import resolve_regulation

		resolve = lambda batch: resolve_regulation(demo.ENGINEERING, "B.E. ECE", batch)  # noqa: E731
		self.assertEqual(resolve("2021-22"), regulation_name("AU-R2021", demo.ENGINEERING))
		self.assertEqual([resolve(f"{y}-{str(y + 1)[-2:]}") for y in (2022, 2023, 2024, 2025)], [regulation_name("R2022", demo.ENGINEERING)] * 4)
		self.assertEqual(resolve("2026-27"), regulation_name("R2026", demo.ENGINEERING))
		self.assertEqual(frappe.db.get_value("Regulation", regulation_name("AS-R2022", demo.ARTS), "company"), demo.ARTS)

	def test_users_have_company_permission_and_roles(self):
		principal, warden = demo.email("principal"), demo.email("warden")
		self.assertEqual(
			frappe.get_all("User Permission", filters={"user": principal, "allow": "Company"}, pluck="for_value"),
			[demo.ENGINEERING],
		)
		self.assertEqual(
			set(frappe.get_all("User Permission", filters={"user": warden, "allow": "Company"}, pluck="for_value")),
			set(demo.ALL_COMPANIES),
		)
		self.assertIn("Principal", frappe.get_roles(principal))
		self.assertIn("HOD", frappe.get_roles(demo.email("hod_cse")))
		self.assertIn("Accounts User", frappe.get_roles(demo.email("accounts")))

	def test_position_holders_resolve(self):
		self.assertEqual(resolve_position("PRINCIPAL", demo.ENGINEERING), [demo.email("principal")])
		cse = demo.department_name(demo.CSE_DEPARTMENT, demo.ENGINEERING)
		self.assertEqual(resolve_position("HOD", cse), [demo.email("hod_cse")])

	def test_faculty_are_instructors_and_student_1_is_linked(self):
		for username in demo.INSTRUCTORS:
			employee = demo.employee_of(username)
			self.assertTrue(frappe.db.exists("Instructor", {"employee": employee, "oc_company": demo.ENGINEERING}))
		student = frappe.db.get_value("Student", {"user": demo.email("student_1")})
		self.assertTrue(student)
		self.assertTrue(frappe.db.exists("Guardian", {"user": demo.email("guardian_1")}))
