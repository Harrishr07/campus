"""M17-01 unit tests: pack availability rules by institution status."""

from frappe.tests import UnitTestCase

from campus.campus_platform.pack_rules import effective_status, status_allows_pack


class TestPackRules(UnitTestCase):
	def test_status_allows_pack(self):
		restricted = ["Autonomous", "Deemed"]
		self.assertFalse(status_allows_pack(restricted, "Affiliated"))
		self.assertTrue(status_allows_pack(restricted, "Autonomous"))
		self.assertTrue(status_allows_pack(restricted, "Deemed"))

	def test_empty_allowed_statuses_means_all(self):
		for status in ("Affiliated", "Autonomous", "Deemed"):
			self.assertTrue(status_allows_pack([], status))

	def test_effective_status_without_date_is_current_status(self):
		self.assertEqual(effective_status("Autonomous", None, "2026-10-04"), "Autonomous")

	def test_effective_status_before_date_is_affiliated(self):
		self.assertEqual(effective_status("Autonomous", "2026-11-01", "2026-10-04"), "Affiliated")

	def test_effective_status_on_and_after_date(self):
		self.assertEqual(effective_status("Autonomous", "2026-10-04", "2026-10-04"), "Autonomous")
		self.assertEqual(effective_status("Deemed", "2026-01-01", "2026-10-04"), "Deemed")
