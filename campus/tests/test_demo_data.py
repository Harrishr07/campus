"""PR-03 tests: the SXCCE demo dataset loads once, loading again creates nothing, the key counts hold, every role user sees data in
its main list, the AISHE export and an AQAR data point have content, and a site that is not a demo site is refused."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from campus.iqac import aishe
from campus.iqac.registry import data_point
from campus.setup import people
from campus.setup.demo_data import load
from campus.setup.pilot import setup_college
from campus.setup.profile import load_profile

PROFILE = load_profile("sxcce")
COLLEGE = PROFILE["college"]["name"]
# role user key -> (DocType of the main list, filters)
MAIN_LISTS = {
	"admissions": "Student Applicant", "office": "Student", "faculty": "Student Group", "hod": "Student",
	"class_advisor": "Student", "coe": "Student Result", "accounts": "Sales Invoice", "principal": "Student",
	"iqac": "Accreditation Cycle", "student": "Student Result", "guardian": "Student",
}  # fmt: skip


class TestDemoData(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		setup_college("sxcce", test_passwords=True)
		cls.first = load("sxcce", 2026)
		cls.second = load("sxcce", 2026)

	def count(self, doctype, **filters):
		return frappe.db.count(doctype, filters)

	def test_loading_again_creates_and_updates_nothing(self):
		self.assertEqual(self.second["created"], {})
		self.assertEqual(self.second["updated"], {})

	def test_key_counts(self):
		self.assertEqual(self.count("Student Applicant", oc_company=COLLEGE), 60)
		self.assertEqual(self.count("Lead", company=COLLEGE), 18)
		self.assertEqual(self.count("Applicant Upload", company=COLLEGE), 1)
		self.assertEqual(self.count("Student Applicant", oc_company=COLLEGE, application_status="Admitted"), 48)
		self.assertEqual(self.count("Student Applicant", oc_company=COLLEGE, application_status="Approved"), 6)
		self.assertEqual(self.count("Student", oc_company=COLLEGE, oc_batch="2025-26"), 120)
		self.assertEqual(self.count("Student", oc_company=COLLEGE, oc_batch="2026-27", oc_academic_status="Active"), 42)
		self.assertEqual(self.count("Student", oc_company=COLLEGE, oc_academic_status="Admitted"), 6)
		self.assertEqual(self.count("Instructor", oc_company=COLLEGE), 18)
		self.assertEqual(self.count("Curriculum", company=COLLEGE, status="Effective"), 6)
		self.assertEqual(self.count("Exam Session", company=COLLEGE, status="Published"), 2)
		self.assertEqual(self.count("Student Result", company=COLLEGE, is_latest=1), 240)

	def test_fees_are_paid_in_part_and_outstanding_in_part(self):
		invoices = frappe.get_all("Sales Invoice", {"company": COLLEGE, "docstatus": 1}, ["grand_total", "outstanding_amount"])
		self.assertEqual(len(invoices), 42)
		self.assertTrue(any(i.outstanding_amount == 0 for i in invoices))
		self.assertTrue(any(i.outstanding_amount == i.grand_total for i in invoices))
		self.assertTrue(any(0 < i.outstanding_amount < i.grand_total for i in invoices))

	def test_the_first_year_has_cgpa_and_arrears(self):
		results = frappe.get_all("Student Result", {"company": COLLEGE, "is_latest": 1}, ["cgpa", "arrear_count"])
		self.assertGreater(sum(1 for r in results if r.cgpa), len(results) * 0.9)
		self.assertTrue(any(r.arrear_count for r in results))
		self.assertTrue(any(not r.arrear_count for r in results))

	def test_the_current_term_has_attendance_leave_and_internal_marks(self):
		self.assertGreater(self.count("Student Attendance", status="Leave"), 0)
		kinds = set(frappe.get_all("Student Leave Application", {"docstatus": 1}, pluck="oc_leave_kind"))
		self.assertTrue({"Medical", "On Duty"} <= kinds)
		self.assertEqual(self.count("Mark Sheet Entry", company=COLLEGE), 108)

	def test_every_role_user_sees_data_in_its_main_list(self):
		domain = PROFILE["user_domain"]
		self.addCleanup(frappe.set_user, "Administrator")
		for key, doctype in MAIN_LISTS.items():
			frappe.set_user(f"{key}@{domain}")
			self.assertTrue(frappe.get_list(doctype, limit=1), f"{key} sees no {doctype}")

	def test_services_exist(self):
		self.assertEqual(self.count("Counselling Note", is_confidential=0), 1)
		self.assertEqual(self.count("Parent Interaction"), 1)
		self.assertEqual(self.count("Placement Drive", company=COLLEGE), 1)
		self.assertTrue(self.count("Drive Registration", company=COLLEGE) > 0)
		self.assertEqual(self.count("Degree Awarding Authority", company=COLLEGE), 6)
		self.assertEqual(self.count("Official Document", company=COLLEGE), 6)
		self.assertEqual(self.count("Scholarship Application"), 1)

	def test_aishe_export_and_an_aqar_data_point_have_content(self):
		sections = aishe.build(COLLEGE, "2025-26")
		for name in ("Programmes", "Enrolment", "Faculty"):
			self.assertTrue(sections[name]["rows"], name)
		self.assertGreater(data_point("total_students", COLLEGE, "2025-26")["value"], 0)

	def test_personal_data_is_synthetic(self):
		domain = PROFILE["user_domain"]
		self.assertFalse(frappe.db.count("Student", {"oc_company": COLLEGE, "student_email_id": ["not like", f"%@{domain}"]}))
		self.assertFalse(frappe.db.count("Student", {"oc_company": COLLEGE, "student_mobile_number": ["not like", "0%"]}))
		self.assertFalse(frappe.db.count("Student", {"oc_company": COLLEGE, "aadhaar_number": ["is", "set"]}) if frappe.db.has_column("Student", "aadhaar_number") else 0)


class TestDemoGuard(IntegrationTestCase):
	def test_a_site_that_is_not_a_demo_site_is_refused(self):
		with patch.object(people, "test_passwords_allowed", return_value=False):
			with patch("campus.setup.demo_data.pilot_people.test_passwords_allowed", return_value=False):
				with self.assertRaisesRegex(frappe.ValidationError, "developer-mode or demo sites only"):
					load("sxcce", 2026)
