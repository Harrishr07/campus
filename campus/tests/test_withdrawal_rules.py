"""M06-01, M05-03 unit tests: exam withdrawal rules, break of study limits, the bridge course kind, and the T12
classification reading a withdrawal as no appearance."""

from datetime import date

from frappe.tests import UnitTestCase

from campus.examinations import registration_rules, rules
from campus.student_services import withdrawal_rules as wr

EXAM = date(2026, 11, 2)


class TestWithdrawalRefusal(UnitTestCase):
	def test_days_after_exam(self):
		self.assertEqual(wr.days_after_exam(EXAM, date(2026, 11, 12)), 10)
		self.assertEqual(wr.days_after_exam(EXAM, date(2026, 11, 13)), 11)
		self.assertEqual(wr.days_after_exam(EXAM, date(2026, 10, 30)), -3)  # before the exam

	def test_first_withdrawal_within_the_window_is_allowed(self):
		self.assertIsNone(wr.withdrawal_refusal(0, 10, 10, special_case=False))
		self.assertIsNone(wr.withdrawal_refusal(0, -3, 10, special_case=False))

	def test_a_second_withdrawal_in_the_programme_is_refused(self):
		self.assertEqual(wr.withdrawal_refusal(1, 0, 10, special_case=False), wr.REPEAT)

	def test_the_special_case_does_not_lift_once_per_programme(self):
		self.assertEqual(wr.withdrawal_refusal(1, 0, 10, special_case=True), wr.REPEAT)

	def test_eleven_days_after_the_exam_is_late(self):
		self.assertEqual(wr.withdrawal_refusal(0, 11, 10, special_case=False), wr.LATE)

	def test_the_special_case_lifts_the_window(self):
		self.assertIsNone(wr.withdrawal_refusal(0, 11, 10, special_case=True))

	def test_the_window_is_the_record_value(self):
		self.assertIsNone(wr.withdrawal_refusal(0, 14, 15, special_case=False))
		self.assertEqual(wr.withdrawal_refusal(0, 6, 5, special_case=False), wr.LATE)


class TestWithdrawalCode(UnitTestCase):
	def test_the_regulation_code_comes_from_the_scheme(self):
		self.assertEqual(wr.withdrawal_code(["U", "SA", "AB", "WD"], rules.WITHDRAWAL_CODES), "WD")
		self.assertEqual(wr.withdrawal_code(["U", "SA", "AB", "WC"], rules.WITHDRAWAL_CODES), "WC")
		self.assertEqual(wr.withdrawal_code(["U", "W"], rules.WITHDRAWAL_CODES), "W")

	def test_a_scheme_without_a_withdrawal_code_gives_none(self):
		self.assertIsNone(wr.withdrawal_code(["U", "SA", "AB"], rules.WITHDRAWAL_CODES))


class TestWithdrawalIsNotAnAttempt(UnitTestCase):
	"""The Result Run writes result WD and grade WD/WC; T12 must read both as no appearance."""

	def test_distinction_survives_a_withdrawal(self):
		for grade in ("WD", "WC"):
			self.assertTrue(rules.passed_at_first_appearance({"C1": [wr.WITHDRAWN, "Pass"], "C2": ["Pass"]}))
			self.assertTrue(rules.passed_at_first_appearance({"C1": [grade, "Pass"]}))
		self.assertFalse(rules.passed_at_first_appearance({"C1": [wr.WITHDRAWN, "Fail", "Pass"]}))

	def test_a_withdrawal_is_not_counted_as_an_attempt(self):
		self.assertEqual(rules.attempt_number([wr.WITHDRAWN], absent_counts_as_attempt=True), 1)
		self.assertEqual(rules.attempt_number([wr.WITHDRAWN, "Fail"], absent_counts_as_attempt=True), 2)

	def test_classify_gives_distinction_after_a_withdrawal(self):
		classes = [
			{"class_name": "First Class with Distinction", "variant": "Regular", "cgpa_min": 8.5,
				"first_appearance_required": 1, "max_years": 0, "max_years_lateral": 0, "break_of_study_included": 1},
		]  # fmt: skip
		first = rules.passed_at_first_appearance({"C1": [wr.WITHDRAWN, "Pass"]})
		self.assertEqual(rules.classify(8.7, classes, first_appearance=first), ("First Class with Distinction", "Regular"))


class TestBreakOfStudy(UnitTestCase):
	def test_break_days_are_inclusive(self):
		self.assertEqual(wr.break_days(date(2026, 6, 1), date(2026, 6, 1)), 1)
		self.assertEqual(wr.break_days(date(2026, 6, 1), date(2027, 5, 31)), 365)

	def test_one_calendar_year_fits_even_across_a_leap_day(self):
		self.assertIsNone(wr.break_refusal(0, wr.break_days(date(2027, 6, 1), date(2028, 5, 31)), 1, 1, False))

	def test_more_than_the_maximum_needs_the_exceptional_year(self):
		self.assertEqual(wr.break_refusal(0, 400, 1, 1, exceptional=False), wr.EXCEEDS)
		self.assertIsNone(wr.break_refusal(0, 400, 1, 1, exceptional=True))

	def test_earlier_breaks_count_towards_the_limit(self):
		self.assertEqual(wr.break_refusal(300, 100, 1, 1, exceptional=False), wr.EXCEEDS)
		self.assertIsNone(wr.break_refusal(300, 66, 1, 1, exceptional=False))

	def test_the_exceptional_year_is_capped_too(self):
		self.assertEqual(wr.break_refusal(0, 2 * wr.YEAR_DAYS + 1, 1, 1, exceptional=True), wr.EXCEEDS)
		self.assertIsNone(wr.break_refusal(0, 2 * wr.YEAR_DAYS, 1, 1, exceptional=True))

	def test_limits_are_record_values(self):
		self.assertIsNone(wr.break_refusal(0, 700, 2, 0, exceptional=False))
		self.assertEqual(wr.break_refusal(0, 400, 1, 0, exceptional=True), wr.EXCEEDS)

	def test_an_end_before_the_start_is_refused(self):
		self.assertEqual(wr.break_refusal(0, 0, 1, 1, exceptional=False), wr.BAD_DATES)


class TestBridgeKind(UnitTestCase):
	def test_a_bridge_course_is_eligible_like_an_arrear(self):
		bridge = registration_rules.BRIDGE
		self.assertEqual(registration_rules.course_eligibility(bridge, shortage=True), registration_rules.ELIGIBLE)
		self.assertEqual(registration_rules.course_eligibility(bridge, False, detained=True), registration_rules.ELIGIBLE)
		self.assertEqual(registration_rules.course_eligibility(bridge, False, debarred=True), registration_rules.DEBARRED)
