"""PR-08 UAT Feedback: testers file and see only their own rows, cannot triage; coordinators see and triage all."""

import frappe
from frappe.tests import IntegrationTestCase

from campus.campus_platform import uat

TESTER_A, TESTER_B = "uat-a@example.com", "uat-b@example.com"
COORDINATOR = "uat-coord@example.com"


def make_login(email, role):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "uat", "send_welcome_email": 0}
		).insert()
	frappe.get_doc("User", email).add_roles(role)


def as_user(user, fn):
	frappe.set_user(user)
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")


def file_feedback(**values):
	doc = {
		"doctype": "UAT Feedback",
		"script": "faculty",
		"step": "4",
		"severity": "High",
		"expected": "e",
		"actual": "a",
		**values,
	}
	return frappe.get_doc(doc).insert()


class TestUATFeedback(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		uat.ensure_uat_roles()
		make_login(TESTER_A, uat.TESTER_ROLE)
		make_login(TESTER_B, uat.TESTER_ROLE)
		make_login(COORDINATOR, uat.COORDINATOR_ROLE)

	def test_scripts_option_matches_the_uat_scripts(self):
		options = frappe.get_meta("UAT Feedback").get_field("script").options.split("\n")
		self.assertEqual(sorted(o for o in options if o), sorted(uat.SCRIPTS))
		scripts = frappe.get_app_path("campus", "..", "docs", "usage", "uat")
		import os

		self.assertEqual(
			sorted(f[:-3] for f in os.listdir(scripts) if f.endswith(".md") and f != "README.md"),
			sorted(uat.SCRIPTS),
		)

	def test_a_tester_files_feedback_with_defaults_and_owns_it(self):
		doc = as_user(TESTER_A, file_feedback)
		self.assertRegex(doc.name, r"^UAT-\d{4}$")
		self.assertEqual((doc.status, doc.tester_role, doc.owner), ("New", TESTER_A, TESTER_A))

	def test_a_tester_sees_only_their_own_rows(self):
		mine = as_user(TESTER_A, file_feedback).name
		theirs = as_user(TESTER_B, file_feedback).name
		seen = as_user(TESTER_A, lambda: frappe.get_list("UAT Feedback", pluck="name"))
		self.assertIn(mine, seen)
		self.assertNotIn(theirs, seen)
		self.assertFalse(as_user(TESTER_A, lambda: frappe.has_permission("UAT Feedback", "read", theirs)))
		self.assertFalse(as_user(TESTER_A, lambda: frappe.has_permission("UAT Feedback", "delete", mine)))

	def test_a_tester_cannot_triage(self):
		name = as_user(TESTER_A, file_feedback).name

		def triage():
			doc = frappe.get_doc("UAT Feedback", name)
			doc.status, doc.coordinator_notes = "Fixed", "done"
			doc.save()

		as_user(TESTER_A, triage)  # permlevel 1 fields are silently kept
		doc = frappe.get_doc("UAT Feedback", name)
		self.assertEqual((doc.status, doc.coordinator_notes), ("New", None))

	def test_a_coordinator_sees_all_and_triages(self):
		name = as_user(TESTER_A, file_feedback).name

		def triage():
			doc = frappe.get_doc("UAT Feedback", name)
			doc.status, doc.coordinator_notes = "Triaged", "looking"
			doc.save()
			return frappe.get_list("UAT Feedback", pluck="name")

		self.assertIn(name, as_user(COORDINATOR, triage))
		self.assertEqual(frappe.db.get_value("UAT Feedback", name, "status"), "Triaged")

	def test_portal_only_roles_get_no_tester_role(self):
		self.assertEqual(uat.tester_roles_for(["Student"]), [])
		self.assertEqual(uat.tester_roles_for(["Guardian", "Student"]), [])
		self.assertEqual(uat.tester_roles_for(["Accounts User"]), [uat.TESTER_ROLE])
