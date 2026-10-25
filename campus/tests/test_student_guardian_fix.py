"""Tests for BUG-07: Guardian dropdown filter and auto-fetch in Student Guardian child table."""

from unittest.mock import MagicMock, patch
import frappe
from frappe.tests.utils import FrappeTestCase

from campus.student_services.setup import setup_student_guardian_fetch
from campus.patches.fix_student_guardian_fetch import execute as run_patch


class TestStudentGuardianFix(FrappeTestCase):
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
