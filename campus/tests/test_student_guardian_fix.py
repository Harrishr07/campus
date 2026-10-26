"""Tests for BUG-07: Guardian dropdown filter and auto-fetch in Student Guardian child table."""

from unittest.mock import MagicMock, patch
import frappe
from frappe.tests.utils import FrappeTestCase

from campus.student_services.setup import setup_student_guardian_fetch
from campus.patches.fix_student_guardian_fetch import execute as run_patch


class TestStudentGuardianFix(FrappeTestCase):
	def setUp(self):
		frappe.db.savepoint("guardian_fetch_test")

	def tearDown(self):
		frappe.db.rollback(save_point="guardian_fetch_test")

	def test_setup_student_guardian_fetch_runs_idempotently(self):
		"""setup_student_guardian_fetch and the patch run without error."""
		setup_student_guardian_fetch()
		run_patch()

	def test_student_guardian_property_setter_applied_when_field_exists(self):
		"""When Student Guardian fields exist, property setters for fetch_from are set."""
		with patch("frappe.db.exists", return_value=True), \
		     patch("frappe.custom.doctype.property_setter.property_setter.make_property_setter") as mock_setter:
			setup_student_guardian_fetch()
			self.assertGreaterEqual(mock_setter.call_count, 1)
			called_doctypes = [call[0][0] for call in mock_setter.call_args_list]
			self.assertTrue(all(dt == "Student Guardian" for dt in called_doctypes))

	def test_guardian_details_fetched_into_student_record(self):
		"""Creating a Guardian, adding to Student, and saving populates fetched name, email and mobile."""
		setup_student_guardian_fetch()

		guardian = frappe.get_doc({
			"doctype": "Guardian",
			"guardian_name": "Test Guardian BUG07",
			"email_address": "guardian_bug07@example.com",
			"mobile_number": "9876543210",
		}).insert()

		student = frappe.get_doc({
			"doctype": "Student",
			"first_name": "Test",
			"last_name": "StudentBUG07",
		})
		student.append("guardians", {
			"guardian": guardian.name,
		})
		student.insert()

		row = student.guardians[0]
		self.assertEqual(row.guardian_name, "Test Guardian BUG07")
		if hasattr(row, "email_address") and frappe.db.has_column("Student Guardian", "email_address"):
			self.assertEqual(row.email_address, "guardian_bug07@example.com")
		if hasattr(row, "mobile_number") and frappe.db.has_column("Student Guardian", "mobile_number"):
			self.assertEqual(row.mobile_number, "9876543210")
