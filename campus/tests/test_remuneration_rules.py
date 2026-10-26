"""M06-04 unit tests: examiner remuneration rate versions, line amounts, the next payroll date and invoice lines."""

from frappe.tests import UnitTestCase
from frappe.utils import getdate

from campus.examinations import remuneration_rules as rr

RATES = [
	{"name": "old", "from_date": "2020-01-01", "rate": 20},
	{"name": "new", "from_date": "2026-01-01", "rate": 25},
]


class TestRateOn(UnitTestCase):
	def test_the_latest_version_in_force_on_the_date_applies(self):
		self.assertEqual(rr.rate_on(RATES, "2026-10-09")["name"], "new")
		self.assertEqual(rr.rate_on(RATES, "2026-01-01")["name"], "new")  # in force from its own date
		self.assertEqual(rr.rate_on(RATES, "2025-12-31")["name"], "old")

	def test_order_of_the_records_does_not_matter(self):
		self.assertEqual(rr.rate_on(list(reversed(RATES)), "2026-10-09")["name"], "new")

	def test_no_rate_before_the_first_version(self):
		self.assertIsNone(rr.rate_on(RATES, "2019-12-31"))
		self.assertIsNone(rr.rate_on([], "2026-10-09"))


class TestLineAmount(UnitTestCase):
	def test_amount_is_count_times_rate_to_the_paisa(self):
		self.assertEqual(rr.line_amount(2, 25), 50)
		self.assertEqual(rr.line_amount(3, 33.333), 100.0)  # 99.999 rounds to two places


class TestNextPayrollDate(UnitTestCase):
	def test_without_a_processed_slip_the_claim_date_is_used(self):
		self.assertEqual(rr.next_payroll_date("2026-10-09", None), getdate("2026-10-09"))

	def test_after_a_processed_slip_the_day_after_it(self):
		self.assertEqual(rr.next_payroll_date("2026-10-09", "2026-10-31"), getdate("2026-11-01"))

	def test_an_older_slip_leaves_the_claim_date(self):
		self.assertEqual(rr.next_payroll_date("2026-10-09", "2026-09-30"), getdate("2026-10-09"))


class TestAmountByItem(UnitTestCase):
	def test_lines_of_one_item_are_added_together(self):
		lines = [{"item": "VAL", "amount": 50}, {"item": "QP", "amount": 1500}, {"item": "VAL", "amount": 60}]
		self.assertEqual(rr.amount_by_item(lines), {"VAL": 110, "QP": 1500})

	def test_a_line_without_an_item_is_reported(self):
		with self.assertRaises(rr.MissingItem) as caught:
			rr.amount_by_item(
				[
					{"item": "VAL", "amount": 50, "activity": "Valuation Round 1"},
					{"item": None, "amount": 1, "activity": "Valuation Round 2"},
				]
			)
		self.assertEqual(caught.exception.activity, "Valuation Round 2")
