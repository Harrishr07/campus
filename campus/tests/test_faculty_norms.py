"""P2-T05 (M07-01) tests: qualification rules of a Faculty Norm, the appointment check on Employee with its
Principal override, norm versioning, Sanctioned Post uniqueness and the Job Applicant flag."""

import frappe
from frappe.tests import UnitTestCase

from campus.faculty.qualification import qualification_shortfalls
from campus.tests import demo
from campus.tests.demo_faculty import NORM_FROM
from campus.tests.utils import CampusTestCase


def profile(**values):
	base = {
		"oc_highest_qualification": "Post Graduate",
		"oc_phd_status": "",
		"oc_net_set": "",
		"oc_prior_teaching_experience": 0,
	}
	return frappe._dict({**base, **values})


def rule(**values):
	base = {
		"minimum_qualification": "Post Graduate",
		"requires_phd": 0,
		"requires_net_set_or_phd": 0,
		"minimum_experience_years": 0,
	}
	return frappe._dict({**base, **values})


class TestQualificationRules(UnitTestCase):
	def test_meeting_every_requirement_has_no_shortfall(self):
		self.assertEqual(qualification_shortfalls(profile(), rule()), [])

	def test_no_rule_for_the_cadre_has_no_shortfall(self):
		self.assertEqual(qualification_shortfalls(profile(oc_highest_qualification="Diploma"), None), [])

	def test_qualification_below_the_minimum(self):
		self.assertEqual(
			len(qualification_shortfalls(profile(oc_highest_qualification="Graduate"), rule())), 1
		)
		self.assertEqual(len(qualification_shortfalls(profile(oc_highest_qualification=""), rule())), 1)

	def test_higher_qualification_meets_a_lower_minimum(self):
		self.assertEqual(qualification_shortfalls(profile(), rule(minimum_qualification="Graduate")), [])

	def test_phd_required(self):
		self.assertEqual(
			len(qualification_shortfalls(profile(oc_phd_status="Pursuing"), rule(requires_phd=1))), 1
		)
		awarded = profile(oc_highest_qualification="Doctorate", oc_phd_status="Awarded")
		self.assertEqual(qualification_shortfalls(awarded, rule(requires_phd=1)), [])

	def test_net_set_or_phd(self):
		needs = rule(requires_net_set_or_phd=1)
		self.assertEqual(len(qualification_shortfalls(profile(), needs)), 1)
		self.assertEqual(qualification_shortfalls(profile(oc_net_set="SET"), needs), [])
		self.assertEqual(
			qualification_shortfalls(
				profile(oc_highest_qualification="Doctorate", oc_phd_status="Awarded"), needs
			),
			[],
		)

	def test_experience_below_the_minimum(self):
		self.assertEqual(
			len(
				qualification_shortfalls(
					profile(oc_prior_teaching_experience=7.5), rule(minimum_experience_years=8)
				)
			),
			1,
		)
		self.assertEqual(
			qualification_shortfalls(
				profile(oc_prior_teaching_experience=8), rule(minimum_experience_years=8)
			),
			[],
		)

	def test_every_failure_is_listed(self):
		failures = qualification_shortfalls(
			profile(oc_highest_qualification="Graduate"),
			rule(requires_phd=1, requires_net_set_or_phd=1, minimum_experience_years=1),
		)
		self.assertEqual(len(failures), 4)


class TestAppointmentCheck(CampusTestCase):
	demo_scale = "small"

	def setUp(self):
		frappe.db.savepoint("faculty_norm_test")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="faculty_norm_test")

	def new_employee(self, **values):
		return frappe.get_doc({
			"doctype": "Employee", "first_name": "P2T05 Faculty", "gender": "Female", "date_of_birth": "1990-01-01",
			"date_of_joining": "2026-06-01", "status": "Active", "company": demo.ENGINEERING,
			"department": demo.department_name(demo.CSE_DEPARTMENT, demo.ENGINEERING), "oc_staff_type": "Teaching",
			"oc_cadre": "Assistant Professor", "oc_highest_qualification": "Graduate", **values,
		})  # fmt: skip

	def test_unqualified_assistant_professor_is_blocked_without_override(self):
		with self.assertRaises(frappe.ValidationError) as raised:
			self.new_employee().insert()
		self.assertIn("Post Graduate", str(raised.exception))

	def test_override_reason_alone_is_not_enough(self):
		with self.assertRaises(frappe.PermissionError):
			self.new_employee(oc_qualification_override_reason="Industry expert").insert()

	def test_principal_override_with_reason_appoints_and_records_the_flag(self):
		employee = self.new_employee(oc_qualification_override_reason="Industry expert, PG in progress")
		frappe.set_user(demo.email("principal"))
		employee.insert(ignore_permissions=True)
		frappe.set_user("Administrator")
		employee.reload()
		self.assertEqual(employee.oc_qualification_override_by, demo.email("principal"))
		self.assertIn("Post Graduate", employee.oc_qualification_shortfall)

	def test_principal_without_reason_is_still_blocked(self):
		frappe.set_user(demo.email("principal"))
		with self.assertRaises(frappe.ValidationError):
			self.new_employee().insert(ignore_permissions=True)

	def test_unrelated_edit_keeps_the_override_but_a_new_qualification_fact_needs_it_again(self):
		employee = self.new_employee(oc_qualification_override_reason="Industry expert")
		frappe.set_user(demo.email("principal"))
		employee.insert(ignore_permissions=True)
		frappe.set_user("Administrator")
		employee.reload()
		employee.cell_number = "9876543210"
		employee.oc_qualification_override_by = "Administrator"  # a client can't forge the approver
		employee.save()
		self.assertEqual(employee.oc_qualification_override_by, demo.email("principal"))
		employee.oc_cadre = "Associate Professor"
		with self.assertRaises(frappe.PermissionError):
			employee.save()

	def test_qualified_appointment_needs_no_override(self):
		employee = self.new_employee(oc_highest_qualification="Post Graduate").insert()
		self.assertFalse(employee.oc_qualification_shortfall)
		self.assertFalse(employee.oc_qualification_override_by)

	def test_non_teaching_staff_are_not_checked(self):
		employee = self.new_employee(oc_staff_type="Non-teaching").insert()
		self.assertFalse(employee.oc_qualification_shortfall)

	def test_the_norm_version_in_force_on_the_joining_date_applies(self):
		later = frappe.copy_doc(
			frappe.get_doc("Faculty Norm", {"company": demo.ENGINEERING, "effective_from": NORM_FROM})
		)
		later.norm_name, later.effective_from = "P2T05 stricter norm", "2026-01-01"
		later.get("cadres", {"cadre": "Assistant Professor"})[0].requires_net_set_or_phd = 1
		later.insert()
		with self.assertRaises(frappe.ValidationError):
			self.new_employee(oc_highest_qualification="Post Graduate").insert()
		self.new_employee(oc_highest_qualification="Post Graduate", date_of_joining="2025-06-01").insert()

	def test_awarded_phd_records_a_doctorate_and_a_doctorate_needs_an_awarded_phd(self):
		employee = self.new_employee(
			oc_highest_qualification="Post Graduate", oc_phd_status="Awarded"
		).insert()
		self.assertEqual(employee.oc_highest_qualification, "Doctorate")
		with self.assertRaises(frappe.ValidationError):
			self.new_employee(oc_highest_qualification="Doctorate", oc_phd_status="Pursuing").insert()

	def test_one_norm_per_company_and_date(self):
		duplicate = frappe.copy_doc(
			frappe.get_doc("Faculty Norm", {"company": demo.ENGINEERING, "effective_from": NORM_FROM})
		)
		duplicate.norm_name = "P2T05 duplicate"
		with self.assertRaises(frappe.DuplicateEntryError):
			duplicate.insert()

	def test_one_sanctioned_post_per_department_cadre_and_year(self):
		post = frappe.get_doc("Sanctioned Post", frappe.get_all("Sanctioned Post", limit=1, pluck="name")[0])
		self.assertEqual(post.company, demo.ENGINEERING)
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.copy_doc(post).insert()

	def test_job_applicant_below_the_norm_is_flagged(self):
		opening = frappe.get_doc({
			"doctype": "Job Opening", "job_title": "P2T05 Assistant Professor", "designation": self.designation(),
			"company": demo.ENGINEERING, "status": "Open", "description": "Teaching post",
		}).insert()  # fmt: skip
		applicant = frappe.get_doc({
			"doctype": "Job Applicant", "applicant_name": "P2T05 Applicant", "email_id": "p2t05-applicant@example.com",
			"job_title": opening.name, "oc_cadre": "Assistant Professor", "oc_highest_qualification": "Graduate",
		}).insert()  # fmt: skip
		self.assertIn("Post Graduate", applicant.oc_qualification_shortfall)
		applicant.oc_highest_qualification = "Post Graduate"
		applicant.save()
		self.assertFalse(applicant.oc_qualification_shortfall)

	def designation(self):
		if not frappe.db.exists("Designation", "Assistant Professor"):
			frappe.get_doc({"doctype": "Designation", "designation_name": "Assistant Professor"}).insert()
		return "Assistant Professor"
