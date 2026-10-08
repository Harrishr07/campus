"""P2-T05 (M07-01, NAAC 2.2.2 / 2.4.1-2.4.3) tests: the faculty reports and data points reproduce the demo fixture.

Fixture (campus/tests/demo_faculty.py, year 2026-27): CSE has a Professor and an Associate Professor with PhDs and
two Assistant Professors without, all joined 2015-06-01; sanctioned posts CSE 1/2/6, ECE 1/1/3; norm SFR 20, 1:2:6.
"""

import frappe

from campus.faculty import staffing
from campus.faculty.report.cadre_ratio import cadre_ratio
from campus.faculty.report.faculty_vs_sanctioned_posts import faculty_vs_sanctioned_posts
from campus.faculty.report.phd_faculty import phd_faculty
from campus.faculty.report.student_teacher_ratio import student_teacher_ratio
from campus.faculty.report.teaching_experience import teaching_experience
from campus.iqac import registry
from campus.tests import demo
from campus.tests.demo_faculty import YEAR
from campus.tests.utils import CampusTestCase

CSE = f"{demo.CSE_DEPARTMENT} - DCE"  # demo.department_name, which needs the company to exist already
ECE = f"{demo.ECE_DEPARTMENT} - DCE"
FILTERS = {"company": demo.ENGINEERING, "academic_year": YEAR}


def run(report, **extra):
	return report.execute({**FILTERS, **extra})[1]


def point(key, department=None):
	return registry.data_point(key, demo.ENGINEERING, YEAR, department)


def students(department):
	return point("total_students", department)["value"]


class TestFacultyReports(CampusTestCase):
	demo_scale = "small"

	def test_faculty_vs_sanctioned_posts(self):
		self.assertEqual(CSE, demo.department_name(demo.CSE_DEPARTMENT, demo.ENGINEERING))
		rows = {(r["department"], r["cadre"]): (r["sanctioned"], r["filled"], r["vacant"]) for r in run(faculty_vs_sanctioned_posts)}
		self.assertEqual(rows, {
			(CSE, "Professor"): (1, 1, 0), (CSE, "Associate Professor"): (2, 1, 1), (CSE, "Assistant Professor"): (6, 2, 4),
			(ECE, "Professor"): (1, 0, 1), (ECE, "Associate Professor"): (1, 0, 1), (ECE, "Assistant Professor"): (3, 0, 3),
		})  # fmt: skip
		self.assertEqual((point("sanctioned_posts")["value"], point("full_time_teachers")["value"]), (14, 4))
		self.assertEqual(point("full_time_teachers", ECE)["value"], 0)

	def test_phd_faculty(self):
		rows = {r["department"]: (r["teachers"], r["phd"], r["percent"]) for r in run(phd_faculty)}
		self.assertEqual(rows, {CSE: (4, 2, 50.0)})
		phd = point("phd_teachers")
		self.assertEqual(phd["value"], 2)
		self.assertEqual({r["name"] for r in phd["records"]}, {demo.employee_of("hod_cse"), demo.employee_of("faculty_1")})

	def test_teaching_experience(self):
		rows = run(teaching_experience)
		self.assertEqual({r["employee"] for r in rows}, {demo.employee_of(u) for u in demo.INSTRUCTORS})
		self.assertEqual({r["years"] for r in rows}, {12.0})  # 2015-06-01 to the end of 2026-27
		self.assertEqual(point("teacher_experience_years")["value"], 48.0)

	def test_student_teacher_ratio(self):
		rows = {r["department"]: r for r in run(student_teacher_ratio)}
		self.assertEqual((rows[CSE]["students"], rows[CSE]["teachers"]), (students(CSE), 4))
		self.assertEqual(rows[CSE]["ratio"], round(students(CSE) / 4, 2))
		self.assertEqual(rows[CSE]["norm"], 20)
		self.assertEqual((rows[ECE]["students"], rows[ECE]["teachers"], rows[ECE]["ratio"]), (students(ECE), 0, None))
		self.assertEqual(point("student_teacher_ratio")["value"], round(point("total_students")["value"] / 4, 2))
		self.assertGreaterEqual(students(CSE), 20)  # 10 B.E. CSE + 10 M.E. CSE in the small demo

	def test_cadre_ratio(self):
		rows = {(r["department"], r["cadre"]): r for r in run(cadre_ratio)}
		cse = rows[(CSE, "Assistant Professor")]
		self.assertEqual((cse["share"], cse["actual"]), (6, 2))
		self.assertEqual(rows[(CSE, "Professor")]["actual"], 1)
		self.assertEqual(rows[(ECE, "Assistant Professor")]["actual"], 0)
		for row in rows.values():
			self.assertEqual(row["shortfall"], max(row["required"] - row["actual"], 0))
		required = -(-students(CSE) // 20)  # ceil(students / SFR), split 1:2:6 with half-up rounding
		self.assertEqual(
			[rows[(CSE, c)]["required"] for c in ("Professor", "Associate Professor", "Assistant Professor")],
			[int(required * share / 9 + 0.5) for share in (1, 2, 6)],
		)

	def test_department_filter_and_other_company(self):
		self.assertEqual({r["department"] for r in run(faculty_vs_sanctioned_posts, department=ECE)}, {ECE})
		self.assertEqual(run(phd_faculty, company=demo.ARTS), [])

	def test_user_without_the_company_sees_nothing(self):
		user = "p2t05-other-college@example.com"
		frappe.db.savepoint("faculty_report_user")
		was_importing, frappe.flags.in_import = frappe.flags.in_import, True  # skip the users-per-minute throttle in a full run
		try:
			if not frappe.db.exists("User", user):
				frappe.get_doc({"doctype": "User", "email": user, "first_name": "other", "send_welcome_email": 0,
					"roles": [{"role": "HR User"}]}).insert()  # fmt: skip
			frappe.flags.in_import = was_importing
			frappe.get_doc({"doctype": "User Permission", "user": user, "allow": "Company", "for_value": demo.ARTS}).insert()
			frappe.set_user(user)
			self.assertEqual(run(faculty_vs_sanctioned_posts), [])
			self.assertEqual(run(teaching_experience), [])
		finally:
			frappe.flags.in_import = was_importing
			frappe.set_user("Administrator")
			frappe.db.rollback(save_point="faculty_report_user")


class TestFacultyFixRound1(CampusTestCase):
	demo_scale = "small"
	LEFT_FIELDS = ("status", "relieving_date")

	def leave(self, username, relieving_date):
		frappe.db.set_value("Employee", demo.employee_of(username), {"status": "Left", "relieving_date": relieving_date})

	def teachers(self):
		return {t.name for t in staffing.teachers(demo.ENGINEERING, YEAR)}

	def test_left_without_a_relieving_date_is_not_a_teacher(self):
		self.leave("faculty_3", None)
		self.assertNotIn(demo.employee_of("faculty_3"), self.teachers())
		self.assertEqual(point("full_time_teachers")["value"], 3)

	def test_left_before_the_year_started_is_not_a_teacher(self):
		self.leave("faculty_3", "2026-05-31")  # 2026-27 starts on 2026-06-01
		self.assertNotIn(demo.employee_of("faculty_3"), self.teachers())

	def test_left_during_the_year_still_counts_for_it(self):
		self.leave("faculty_3", "2026-09-30")
		self.assertIn(demo.employee_of("faculty_3"), self.teachers())
		self.assertEqual(point("full_time_teachers")["value"], 4)

	def test_report_lists_left_employees_without_a_date_as_a_data_issue(self):
		self.leave("faculty_3", None)
		message = teaching_experience.execute(FILTERS)[2]
		self.assertIn(demo.employee_of("faculty_3"), message)

	def test_reports_respect_employee_user_permissions(self):
		user = "p2t05-cse-only@example.com"
		frappe.db.set_value("Employee", demo.employee_of("faculty_3"), "department", ECE)
		frappe.db.savepoint("cse_only_user")
		was_importing, frappe.flags.in_import = frappe.flags.in_import, True
		try:
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "cse", "send_welcome_email": 0, "roles": [{"role": "HR User"}]}).insert()
			frappe.flags.in_import = was_importing
			frappe.get_doc({"doctype": "User Permission", "user": user, "allow": "Department", "for_value": CSE}).insert()
			frappe.set_user(user)
			names = {r["employee"] for r in run(teaching_experience)}
		finally:
			frappe.flags.in_import = was_importing
			frappe.set_user("Administrator")
			frappe.db.rollback(save_point="cse_only_user")
		self.assertEqual(names, {demo.employee_of(u) for u in ("hod_cse", "faculty_1", "faculty_2")})

	def test_sensitive_fields_are_permlevel_one_for_hr_and_the_principal(self):
		meta = frappe.get_meta("Employee")
		for fieldname in ("oc_highest_qualification", "oc_phd_status", "oc_phd_awarded_on", "oc_net_set", "oc_prior_teaching_experience",
			"oc_aicte_faculty_id", "oc_qualification_shortfall", "oc_qualification_override_reason", "oc_qualification_override_by"):  # fmt: skip
			self.assertEqual(meta.get_field(fieldname).permlevel, 1, fieldname)
		for role in ("HR Manager", "HR User", "Principal"):
			self.assertTrue(frappe.db.exists("Custom DocPerm", {"parent": "Employee", "role": role, "permlevel": 1, "read": 1, "write": 1}), role)

	def test_cadre_is_mandatory_for_teaching_staff(self):
		self.assertEqual(frappe.get_meta("Employee").get_field("oc_cadre").mandatory_depends_on, 'eval:doc.oc_staff_type=="Teaching"')
