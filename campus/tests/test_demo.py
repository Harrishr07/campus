"""P1-T02 tests: the standard demo data builder is complete, correct and idempotent."""

import frappe
from frappe.tests import UnitTestCase

from campus.campus_platform.api import get_regulation, resolve_position
from campus.campus_platform.doctype.regulation.regulation import regulation_name
from campus.tests import demo
from campus.tests.utils import CampusTestCase

DEMO_DOCTYPES = ["Academic Year", "Academic Term", "Department", "Employee", "Instructor"]


def snapshot():
	counts = demo.counts()
	for doctype in [
		*DEMO_DOCTYPES,
		"Program Enrollment",
		"Position Holder",
		"Institution Profile",
		"Shared Service Agreement",
		"User Permission",
		"Student Category",
		"Guardian",
	]:
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

	def test_reserved_categories_are_flagged(self):
		flagged = set(
			frappe.get_all(
				"Student Category", {"name": ["in", demo.CATEGORIES], "oc_is_reserved": 1}, pluck="name"
			)
		)
		self.assertEqual(flagged, {"BC", "MBC", "SC", "ST"})

	def test_cse_r2022_curriculum_is_a_draft_with_derived_credits(self):
		self.assertEqual(demo.counts()["Curriculum"], 1)
		curriculum = frappe.get_doc("Curriculum", {"program": "B.E. CSE"})
		self.assertEqual(curriculum.status, "Draft")
		self.assertEqual(curriculum.total_credits, 24)  # six 4-credit courses
		self.assertEqual(curriculum.courses[1].credits, 4)  # 3-0-2 under R2022

	def test_company_hierarchy_and_profiles(self):
		self.assertTrue(frappe.db.get_value("Company", demo.TRUST, "is_group"))
		for college in (demo.ENGINEERING, demo.ARTS):
			self.assertEqual(frappe.db.get_value("Company", college, "parent_company"), demo.TRUST)
		profile = frappe.get_doc("Institution Profile", demo.ENGINEERING)
		status = (profile.institution_status, str(profile.status_effective_from))
		self.assertEqual(status, ("Autonomous", "2022-05-26"))
		self.assertEqual(
			frappe.db.get_value("Institution Profile", demo.ARTS, "institution_status"), "Affiliated"
		)

	def test_students_resolve_to_effective_regulation_with_category_spread(self):
		students = frappe.get_all(
			"Student",
			filters={"student_email_id": ["like", f"%@{demo.DOMAIN}"]},
			fields=["name", "oc_regulation", "oc_batch", "oc_company"],
		)
		categories = frappe.get_all(
			"Program Enrollment",
			filters={"student": ["in", [s.name for s in students]]},
			pluck="student_category",
		)
		self.assertEqual({s.oc_regulation for s in students}, {regulation_name("R2026", demo.ENGINEERING)})
		self.assertEqual({s.oc_batch for s in students}, {"2026-27"})
		self.assertEqual({s.oc_company for s in students}, {demo.ENGINEERING})
		self.assertEqual(set(categories), {"OC", "BC", "MBC", "SC"})  # first 10 of each batch
		self.assert_each_program_batch_has_mixed_categories()
		self.assertEqual(get_regulation(students[0].name), regulation_name("R2026", demo.ENGINEERING))

	def assert_each_program_batch_has_mixed_categories(self):
		rows = frappe.db.sql(
			"""select pe.program, pe.academic_year, count(distinct pe.student_category)
			from `tabProgram Enrollment` pe join tabStudent s on s.name = pe.student
			where s.student_email_id like %s and pe.docstatus = 1 group by 1, 2""",
			(f"%@{demo.DOMAIN}",),
		)
		self.assertEqual(len(rows), 3)
		for program, year, distinct in rows:
			self.assertGreater(distinct, 1, f"{program} {year} has a single category")

	def test_interrupted_run_is_repaired(self):
		email = demo.student_email("ece", 2026, 3)
		student = frappe.db.get_value("Student", {"student_email_id": email})
		enrollment = frappe.db.get_value("Program Enrollment", {"student": student, "docstatus": 1})
		frappe.get_doc("Program Enrollment", enrollment).cancel()
		frappe.delete_doc("Program Enrollment", enrollment, force=True)
		frappe.db.set_value("Student", student, "oc_regulation", None)
		demo.make_demo("small")
		repaired = frappe.get_all(
			"Program Enrollment", filters={"student": student, "docstatus": 1}, fields=["student_category"]
		)
		self.assertEqual([r.student_category for r in repaired], [demo.category_for(3)])
		self.assertEqual(frappe.db.get_value("Student", student, "oc_regulation"), "R2026-DCE")

	def test_regulation_name_needs_company_and_abbreviation(self):
		for code, company in (("R1", None), ("R1", "No Such Company"), (None, demo.ENGINEERING)):
			with self.subTest(code=code, company=company), self.assertRaises(frappe.ValidationError):
				regulation_name(code, company)

	def test_regulations_cover_programs_per_batch(self):
		from campus.campus_platform.regulation_rules import resolve_regulation

		resolve = lambda batch: resolve_regulation(demo.ENGINEERING, "B.E. ECE", batch)  # noqa: E731
		self.assertEqual(resolve("2021-22"), regulation_name("AU-R2021", demo.ENGINEERING))
		middle_years = [resolve(demo.year_name(year)) for year in (2022, 2023, 2024, 2025)]
		self.assertEqual(middle_years, [regulation_name("R2022", demo.ENGINEERING)] * 4)
		self.assertEqual(resolve("2026-27"), regulation_name("R2026", demo.ENGINEERING))
		arts_regulation = regulation_name("AS-R2022", demo.ARTS)
		self.assertEqual(frappe.db.get_value("Regulation", arts_regulation, "company"), demo.ARTS)

	def test_users_have_company_permission_and_roles(self):
		principal, warden = demo.email("principal"), demo.email("warden")
		self.assertEqual(
			frappe.get_all(
				"User Permission", filters={"user": principal, "allow": "Company"}, pluck="for_value"
			),
			[demo.ENGINEERING],
		)
		self.assertEqual(
			set(
				frappe.get_all(
					"User Permission", filters={"user": warden, "allow": "Company"}, pluck="for_value"
				)
			),
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
			self.assertTrue(
				frappe.db.exists("Instructor", {"employee": employee, "oc_company": demo.ENGINEERING})
			)
		student = frappe.db.get_value("Student", {"user": demo.email("student_1")})
		self.assertTrue(student)
		self.assertTrue(frappe.db.exists("Guardian", {"user": demo.email("guardian_1")}))


class TestDemoHelpers(UnitTestCase):
	"""Pure helpers behind the "full" scale, covered without the 90 s run."""

	def test_student_email_is_unique_across_the_full_set(self):
		emails = {
			demo.student_email(slug, batch, number)
			for _program, (_company, _dept, slug) in demo.PROGRAMS.items()
			if slug
			for batch in demo.FULL_BATCHES
			for number in range(1, demo.STUDENTS_PER_BATCH["full"] + 1)
		}
		self.assertEqual(len(emails), 3 * 5 * 60)
		self.assertEqual(demo.student_email("cse", 2026, 1), demo.email("student_1"))
		self.assertEqual(demo.student_email("ece", 2023, 7), "ece-2023-007@demo.campus.test")

	def test_category_cycle_spreads_every_batch(self):
		cycle = [demo.category_for(n) for n in range(1, 61)]
		self.assertEqual(set(cycle), set(demo.CATEGORIES))
		spread = {c: cycle.count(c) for c in demo.CATEGORIES}
		self.assertEqual(spread, {"OC": 18, "BC": 15, "MBC": 12, "SC": 12, "ST": 3})
		self.assertEqual(len({demo.category_for(n) for n in range(1, 11)}), 4)  # even a small batch is mixed

	def test_batch_to_regulation_mapping(self):
		codes = {
			batch: demo.expected_regulation_code(batch) for batch in (2021, 2022, 2023, 2024, 2025, 2026)
		}
		self.assertEqual(
			codes,
			{2021: "AU-R2021", 2022: "R2022", 2023: "R2022", 2024: "R2022", 2025: "R2022", 2026: "R2026"},
		)
