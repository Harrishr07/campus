"""M06-06 unit tests of the pure revaluation rules (P2-T20): the window from publication, the fee and the change."""

from frappe.tests import UnitTestCase

from campus.examinations import revaluation_rules as rules


class TestWindow(UnitTestCase):
	def test_the_window_opens_on_the_publication_day_and_closes_after_its_last_day(self):
		self.assertTrue(rules.window_open("2026-10-01", "2026-10-01", 10))
		self.assertTrue(rules.window_open("2026-10-01", "2026-10-11", 10))  # day 10
		self.assertFalse(rules.window_open("2026-10-01", "2026-10-12", 10))  # day 11

	def test_no_application_before_publication_or_without_a_window(self):
		self.assertFalse(rules.window_open("2026-10-01", "2026-09-30", 10))
		self.assertFalse(rules.window_open("2026-10-01", "2026-10-01", 0))
		self.assertFalse(rules.window_open("2026-10-01", "2026-10-01", None))
		self.assertFalse(rules.window_open(None, "2026-10-01", 10))


class TestFee(UnitTestCase):
	def test_the_fee_is_the_rate_per_course(self):
		self.assertEqual(rules.fee_total(500, 3), 1500)
		self.assertEqual(rules.fee_total(None, 3), 0)
		self.assertEqual(rules.fee_total(250.5, 0), 0)


class TestChange(UnitTestCase):
	def test_the_direction_of_a_change(self):
		self.assertEqual(rules.change_direction(26.4, 40), rules.INCREASED)
		self.assertEqual(rules.change_direction(40, 26.4), rules.DECREASED)
		self.assertEqual(rules.change_direction(40, 40.0), rules.UNCHANGED)

	def test_the_grievance_ratio(self):
		self.assertEqual(rules.grievance_pct(1, 3), 33.33)
		self.assertEqual(rules.grievance_pct(0, 0), 0)
