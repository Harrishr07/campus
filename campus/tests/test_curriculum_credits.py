"""P1-T12 unit tests (M03-01): credit derivation, category totals, range and shortfall checks."""

from types import SimpleNamespace

from frappe.tests import UnitTestCase

from campus.curriculum.credit_rules import (
	category_totals,
	credit_shortfalls,
	derive_credits,
	range_problem,
)

R2022 = SimpleNamespace(
	lecture_credit_per_period=1, tutorial_credit_per_period=1, practical_credit_per_period=0.5
)


class TestCreditRules(UnitTestCase):
	def test_three_zero_two_is_four_credits(self):
		self.assertEqual(derive_credits(3, 0, 2, R2022), 4)

	def test_each_component_uses_its_own_rate(self):
		self.assertEqual(derive_credits(3, 1, 0, R2022), 4)
		self.assertEqual(derive_credits(0, 0, 4, R2022), 2)
		self.assertEqual(derive_credits(0, 0, 3, R2022), 1.5)

	def test_rates_come_from_the_rule(self):
		other = SimpleNamespace(
			lecture_credit_per_period=2, tutorial_credit_per_period=0, practical_credit_per_period=1
		)
		self.assertEqual(derive_credits(3, 1, 2, other), 8)

	def test_blank_periods_count_as_zero(self):
		self.assertEqual(derive_credits(None, None, 2, R2022), 1)

	def test_category_totals_sum_per_category_and_skip_uncounted(self):
		rows = [("PCC", 4), ("PCC", 3), ("BSC", 4), ("MC", 0), ("AC", 3)]
		totals, counted = category_totals(rows, counts={"PCC": 1, "BSC": 1, "MC": 0, "AC": 0})
		self.assertEqual(totals, {"PCC": 7, "BSC": 4, "MC": 0, "AC": 3})
		self.assertEqual(counted, 11)

	def test_range_problem_branches(self):
		self.assertIsNone(range_problem(167, 165, 170))
		self.assertIsNone(range_problem(165, 165, 170))
		self.assertIsNone(range_problem(170, 165, 170))
		self.assertIn("below", range_problem(160, 165, 170))
		self.assertIn("above", range_problem(171, 165, 170))
		self.assertIsNone(range_problem(500, 0, 0))  # no bounds configured
		self.assertIn("below", range_problem(10, 20, 0))
		self.assertIsNone(range_problem(500, 20, 0))

	def test_shortfalls_list_only_unmet_categories(self):
		totals = {"PCC": 40, "BSC": 20}
		short = credit_shortfalls(totals, {"PCC": 45, "BSC": 20, "HSMC": 10})
		self.assertEqual(short, [("PCC", 40, 45), ("HSMC", 0, 10)])
