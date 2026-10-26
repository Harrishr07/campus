"""M17-01 tests: company scoping on academic records."""

import frappe
from frappe.utils import today

from campus.campus_platform.company_scope import (
	COMPANY_SCOPED_DOCTYPES,
	before_validate,
	validate_linked_companies,
)
from campus.patches.backfill_oc_company import execute as backfill_oc_company
from campus.tests.factories import make_company, make_user
from campus.tests.utils import CampusTestCase

COLLEGE_A = "Campus Test College A"
COLLEGE_B = "Campus Test College B"
USER_A = "campus-college-a@example.com"
USER_B = "campus-college-b@example.com"
USER_TRUST = "campus-trust@example.com"


def make_program(name, company):
	return frappe.get_doc({"doctype": "Program", "program_name": name, "oc_company": company}).insert()


def make_student(first_name, company):
	return frappe.get_doc(
		{
			"doctype": "Student",
			"first_name": first_name,
			"student_email_id": f"{first_name.lower()}@campus-test.example.com",
			"oc_company": company,
		}
	).insert()


def make_academic_year():
	name = "Campus Test AY"
	if not frappe.db.exists("Academic Year", name):
		frappe.get_doc(
			{
				"doctype": "Academic Year",
				"academic_year_name": name,
				"year_start_date": today(),
				"year_end_date": today(),
			}
		).insert()
	return name


class TestCompanyScope(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE_A, "CTA")
		make_company(COLLEGE_B, "CTB")
		make_user(USER_A, [COLLEGE_A])
		make_user(USER_B, [COLLEGE_B])
		make_user(USER_TRUST, [COLLEGE_A, COLLEGE_B])
		cls.academic_year = make_academic_year()
		cls.program_a = make_program("Campus Test BSc A", COLLEGE_A).name
		cls.program_b = make_program("Campus Test BSc B", COLLEGE_B).name
		cls.student_a = make_student("CampusAlice", COLLEGE_A).name
		cls.student_b = make_student("CampusBob", COLLEGE_B).name
		cls.group_a = cls.make_group("Campus Test Group A", cls.program_a)
		cls.group_b = cls.make_group("Campus Test Group B", cls.program_b)

	@classmethod
	def make_group(cls, name, program):
		return (
			frappe.get_doc(
				{
					"doctype": "Student Group",
					"student_group_name": name,
					"academic_year": cls.academic_year,
					"group_based_on": "Batch",
					"program": program,
				}
			)
			.insert()
			.name
		)

	def setUp(self):
		frappe.db.savepoint("company_scope_test")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="company_scope_test")

	def names_visible_to(self, user, doctype, names):
		frappe.set_user(user)
		return set(frappe.get_list(doctype, filters={"name": ["in", names]}, pluck="name"))

	def test_fields_installed_on_all_scoped_doctypes(self):
		for doctype in COMPANY_SCOPED_DOCTYPES:
			df = frappe.get_meta(doctype).get_field("oc_company")
			actual = (df.fieldtype, df.options, df.reqd, df.in_standard_filter)
			self.assertEqual(actual, ("Link", "Company", 1, 1), doctype)
		self.assertIsNone(frappe.get_meta("Fee Schedule").get_field("oc_company"))

	def test_college_user_sees_only_own_college(self):
		cases = [
			("Student", [self.student_a, self.student_b], self.student_a, self.student_b),
			("Program", [self.program_a, self.program_b], self.program_a, self.program_b),
			("Student Group", [self.group_a, self.group_b], self.group_a, self.group_b),
		]
		for doctype, names, own, other in cases:
			self.assertEqual(self.names_visible_to(USER_A, doctype, names), {own}, doctype)
			self.assertEqual(self.names_visible_to(USER_B, doctype, names), {other}, doctype)

	def test_link_search_is_scoped(self):
		from frappe.desk.search import search_link

		frappe.set_user(USER_A)
		results = {r["value"] for r in search_link("Program", "Campus Test BSc")}
		self.assertEqual(results, {self.program_a})

	def test_trust_user_sees_both_colleges(self):
		names = [self.program_a, self.program_b]
		self.assertEqual(self.names_visible_to(USER_TRUST, "Program", names), set(names))

	def test_company_derived_from_program(self):
		group = frappe.get_doc(
			{
				"doctype": "Student Group",
				"student_group_name": "Campus Test Derived",
				"academic_year": self.academic_year,
				"group_based_on": "Batch",
				"program": self.program_b,
				"oc_company": COLLEGE_A,
			}
		).insert()
		self.assertEqual(group.oc_company, COLLEGE_B)

	def test_company_defaults_to_user_default(self):
		frappe.defaults.set_user_default("company", COLLEGE_A, user="Administrator")
		self.addCleanup(frappe.defaults.clear_user_default, "company", "Administrator")
		program = frappe.get_doc({"doctype": "Program", "program_name": "Campus Test Default Co"}).insert()
		self.assertEqual(program.oc_company, COLLEGE_A)

	def test_company_falls_back_to_global_default(self):
		default_before = frappe.db.get_single_value("Global Defaults", "default_company")
		frappe.db.set_single_value("Global Defaults", "default_company", COLLEGE_B)
		self.addCleanup(frappe.db.set_single_value, "Global Defaults", "default_company", default_before)
		program = frappe.get_doc({"doctype": "Program", "program_name": "Campus Test Global Co"}).insert()
		self.assertEqual(program.oc_company, COLLEGE_B)

	def test_course_schedule_company_derived_from_student_group(self):
		schedule = frappe.new_doc("Course Schedule")
		schedule.student_group = self.group_b
		schedule.oc_company = COLLEGE_A
		before_validate(schedule)
		self.assertEqual(schedule.oc_company, COLLEGE_B)

	def test_fee_schedule_rejects_program_of_other_college(self):
		fee_schedule = frappe.new_doc("Fee Schedule")
		fee_schedule.company = COLLEGE_A
		fee_schedule.program = self.program_b
		with self.assertRaises(frappe.ValidationError):
			validate_linked_companies(fee_schedule)
		fee_schedule.program = self.program_a
		validate_linked_companies(fee_schedule)

	def test_course_visibility_is_scoped(self):
		courses = [
			frappe.get_doc({"doctype": "Course", "course_name": f"Campus Test Course {c}", "oc_company": c})
			.insert()
			.name
			for c in (COLLEGE_A, COLLEGE_B)
		]
		self.assertEqual(self.names_visible_to(USER_A, "Course", courses), {courses[0]})
		self.assertEqual(self.names_visible_to(USER_TRUST, "Course", courses), set(courses))

	def make_enrollment(self, student, program):
		return frappe.get_doc(
			{
				"doctype": "Program Enrollment",
				"student": student,
				"program": program,
				"academic_year": self.academic_year,
				"enrollment_date": today(),
			}
		)

	def test_program_enrollment_cross_company_rejected(self):
		enrollment = self.make_enrollment(self.student_b, self.program_a)
		with self.assertRaises(frappe.ValidationError) as ctx:
			enrollment.insert()
		message = str(ctx.exception)
		self.assertIn(self.student_b, message)
		self.assertIn(COLLEGE_B, message)
		self.assertIn(COLLEGE_A, message)

	def test_program_enrollment_same_company_accepted(self):
		enrollment = self.make_enrollment(self.student_a, self.program_a).insert()
		self.assertEqual(enrollment.oc_company, COLLEGE_A)

	def test_student_group_rejects_student_of_other_college(self):
		group = frappe.get_doc("Student Group", self.group_a)
		group.append("students", {"student": self.student_b, "student_name": "CampusBob", "active": 1})
		with self.assertRaises(frappe.ValidationError):
			group.save()

	def test_student_group_accepts_own_student(self):
		group = frappe.get_doc("Student Group", self.group_a)
		group.append("students", {"student": self.student_a, "student_name": "CampusAlice", "active": 1})
		group.save()
		self.assertEqual(len(group.students), 1)

	def test_backfill_patch_is_rerunnable(self):
		default_before = frappe.db.get_single_value("Global Defaults", "default_company")
		frappe.db.set_single_value("Global Defaults", "default_company", COLLEGE_A)
		self.addCleanup(frappe.db.set_single_value, "Global Defaults", "default_company", default_before)
		frappe.db.set_value("Program", self.program_a, "oc_company", None)
		frappe.db.set_value("Student", self.student_a, "oc_company", "")
		frappe.db.set_value("Program", self.program_b, "oc_company", COLLEGE_B)

		backfill_oc_company()
		backfill_oc_company()

		self.assertEqual(frappe.db.get_value("Program", self.program_a, "oc_company"), COLLEGE_A)
		self.assertEqual(frappe.db.get_value("Student", self.student_a, "oc_company"), COLLEGE_A)
		self.assertEqual(frappe.db.get_value("Program", self.program_b, "oc_company"), COLLEGE_B)
		for doctype in COMPANY_SCOPED_DOCTYPES:
			unset = frappe.db.count(doctype, {"oc_company": ["in", ["", None]]})
			self.assertEqual(unset, 0, doctype)

	def test_backfill_without_default_company_is_a_noop(self):
		default_before = frappe.db.get_single_value("Global Defaults", "default_company")
		frappe.db.set_single_value("Global Defaults", "default_company", None)
		self.addCleanup(frappe.db.set_single_value, "Global Defaults", "default_company", default_before)
		frappe.db.set_value("Program", self.program_a, "oc_company", None)
		backfill_oc_company()
		self.assertFalse(frappe.db.get_value("Program", self.program_a, "oc_company"))
