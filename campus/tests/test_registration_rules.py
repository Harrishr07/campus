"""P1-T13 unit tests (M03-04): every pure registration rule at the R2022 values."""

from frappe.tests import UnitTestCase
from frappe.utils import getdate

from campus.curriculum import registration_rules as rules
from campus.curriculum.api import prerequisites_met


class Rule:
	"""Registration Rule values of R2022 (a plain object: the checks never touch the database)."""

	add_from_semester = 5
	max_add_credits = 6
	max_add_courses = 2


PREFIX = rules.clause("R2022", "6.1")
EXCLUDED = rules.excluded_types("Arrear\nDropped")


class TestRegistrationRules(UnitTestCase):
	def test_clause_prefix_cites_the_clause_when_known(self):
		self.assertEqual(rules.clause("R2022", "6.1"), "R2022 cl. 6.1: ")
		self.assertEqual(rules.clause("R2022", None), "R2022: ")

	def test_excluded_types_parse_lines_and_commas(self):
		self.assertEqual(rules.excluded_types("Arrear\nDropped"), {"Arrear", "Dropped"})
		self.assertEqual(rules.excluded_types("Arrear, Dropped"), {"Arrear", "Dropped"})
		self.assertEqual(rules.excluded_types(None), set())

	def test_arrear_and_dropped_credits_do_not_count(self):
		rows = [("Regular", 30), ("Arrear", 8), ("Dropped", 4), ("Additional", 6)]
		self.assertEqual(rules.counted_credits(rows, EXCLUDED), 36)

	def test_credit_limit_at_36_passes_and_37_fails_with_clause(self):
		self.assertEqual(rules.credit_limit_problems([("Regular", 36)], 36, EXCLUDED, PREFIX), [])
		problems = rules.credit_limit_problems([("Regular", 37)], 36, EXCLUDED, PREFIX)
		self.assertEqual(len(problems), 1)
		self.assertIn("R2022 cl. 6.1: 37 credits registered; the maximum is 36", problems[0])

	def test_credit_limit_of_zero_means_no_limit(self):
		self.assertEqual(rules.credit_limit_problems([("Regular", 99)], 0, EXCLUDED, PREFIX), [])

	def test_drop_deadline_is_term_start_plus_days_unless_overridden(self):
		self.assertEqual(rules.drop_deadline("2022-06-01", 30), getdate("2022-07-01"))
		self.assertEqual(rules.drop_deadline("2022-06-01", 30, "2022-06-10"), getdate("2022-06-10"))

	def test_drop_of_six_credits_on_the_last_day_is_allowed(self):
		deadline = getdate("2022-07-01")
		self.assertEqual(rules.drop_problems([("Dropped", 6)], "2022-07-01", deadline, 6, PREFIX), [])

	def test_drop_of_seven_credits_fails(self):
		problems = rules.drop_problems([("Dropped", 4), ("Dropped", 3)], "2022-06-10", "2022-07-01", 6, PREFIX)
		self.assertEqual(len(problems), 1)
		self.assertIn("7 credits dropped; at most 6", problems[0])

	def test_drop_after_the_deadline_fails(self):
		problems = rules.drop_problems([("Dropped", 3)], "2022-07-02", "2022-07-01", 6, PREFIX)
		self.assertEqual(len(problems), 1)
		self.assertIn("only until 2022-07-01", problems[0])

	def test_no_drop_rows_means_no_drop_problems(self):
		self.assertEqual(rules.drop_problems([("Regular", 40)], "2030-01-01", "2022-07-01", 6, PREFIX), [])

	def test_additional_courses_need_semester_five(self):
		problems = rules.add_problems([("Additional", 3)], 4, Rule, PREFIX)
		self.assertIn("from semester 5", problems[0])
		self.assertEqual(rules.add_problems([("Additional", 3)], 5, Rule, PREFIX), [])

	def test_additional_credits_capped_at_six(self):
		problems = rules.add_problems([("Additional", 4), ("Additional", 3)], 5, Rule, PREFIX)
		self.assertEqual(len(problems), 1)
		self.assertIn("7 additional credits; at most 6", problems[0])

	def test_additional_courses_capped_at_two(self):
		problems = rules.add_problems([("Additional", 2)] * 3, 6, Rule, PREFIX)
		self.assertEqual(len(problems), 1)
		self.assertIn("3 additional courses; at most 2", problems[0])

	def test_no_additional_rows_means_no_add_problems(self):
		self.assertEqual(rules.add_problems([("Regular", 4)], 1, Rule, PREFIX), [])

	def test_seat_cap_blocks_at_capacity_and_zero_means_uncapped(self):
		self.assertIn("full", rules.seat_problem("EL", 60, 60, PREFIX))
		self.assertIsNone(rules.seat_problem("EL", 59, 60, PREFIX))
		self.assertIsNone(rules.seat_problem("EL", 500, 0, PREFIX))

	def test_elective_status_below_minimum_only_after_close(self):
		self.assertEqual(rules.elective_status(9, 10, window_closed=True), "Below Minimum")
		self.assertEqual(rules.elective_status(9, 10, window_closed=False), "Filling")
		self.assertEqual(rules.elective_status(10, 10, window_closed=True), "OK")

	def test_term_parity_from_name_then_start_month(self):
		self.assertEqual(rules.term_parity("Odd", "2022-01-01"), 1)
		self.assertEqual(rules.term_parity("Even Semester", "2022-06-01"), 0)
		self.assertEqual(rules.term_parity("Term A", "2022-07-01"), 1)
		self.assertEqual(rules.term_parity("Term B", "2023-01-02"), 0)

	def test_prerequisite_stub_returns_true_until_phase_two(self):
		self.assertTrue(prerequisites_met("any-student", "any-course"))
