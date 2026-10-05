"""M12-02 unit tests: pass rule, grade lookup, SGPA and CGPA maths (hand-computed figures)."""

from frappe.tests import UnitTestCase

from campus.examinations.rules import cgpa, grade, pass_status, round_half_up, sgpa, total_pct
from campus.examinations.seed import GRADES

R2022 = [dict(zip(("letter", "grade_point", "min_mark", "max_mark", "is_pass"), row)) for row in GRADES["R2022"]]
R2026 = [dict(zip(("letter", "grade_point", "min_mark", "max_mark", "is_pass"), row)) for row in GRADES["R2026"]]


class TestPassStatus(UnitTestCase):
	def test_ese_44_pct_with_total_60_fails(self):
		# CIA 33.6/40 + ESE 26.4/60 = 60 total, ESE exactly 44%
		self.assertAlmostEqual(total_pct(33.6, 26.4, 40, 60), 60)
		self.assertFalse(pass_status(33.6, 26.4, 40, 60, 45, 50))

	def test_ese_at_45_pct_and_total_at_50_passes(self):
		self.assertTrue(pass_status(23, 27, 40, 60, 45, 50))  # ESE 45%, total 50%

	def test_total_below_50_fails_even_with_ese_ok(self):
		self.assertFalse(pass_status(10, 28, 40, 60, 45, 50))  # ESE 46.7%, total 38%

	def test_thresholds_are_parameters(self):
		self.assertTrue(pass_status(10, 28, 40, 60, 45, 35))
		self.assertFalse(pass_status(30, 30, 40, 60, 55, 50))  # ESE 50% < 55

	def test_scales_follow_the_course_maxima(self):
		self.assertFalse(pass_status(25, 23, 50, 50, 45, 50))  # total 48
		self.assertTrue(pass_status(25, 25, 50, 50, 45, 50))


class TestGrade(UnitTestCase):
	def test_same_total_differs_by_regulation(self):
		self.assertEqual(grade(63, R2022), ("B+", 7))
		self.assertEqual(grade(63, R2026), ("B", 6.5))

	def test_band_edges(self):
		self.assertEqual(grade(100, R2022), ("O", 10))
		self.assertEqual(grade(91, R2022), ("O", 10))
		self.assertEqual(grade(90, R2022), ("A+", 9))
		self.assertEqual(grade(56, R2022), ("B", 6))
		self.assertEqual(grade(56, R2026), ("C+", 6))
		self.assertEqual(grade(66, R2026), ("B+", 7))
		self.assertEqual(grade(65, R2026), ("B", 6.5))
		self.assertEqual(grade(50, R2022), ("C", 5))
		self.assertEqual(grade(49, R2022), ("U", 0))

	def test_fractional_total_rounds_half_up_to_a_whole_mark(self):
		self.assertEqual(grade(60.5, R2022), ("B+", 7))  # 61
		self.assertEqual(grade(60.49, R2022), ("B", 6))  # 60

	def test_total_outside_every_range_is_an_error(self):
		with self.assertRaises(ValueError):
			grade(101, R2022)


class TestGpa(UnitTestCase):
	def test_sgpa_is_credit_weighted_over_passed_courses(self):
		# (3*7 + 2*8 + 4*9) / 9 = 73/9 = 8.11; the failed 3-credit course is excluded
		courses = [(3, 7, True), (2, 8, True), (4, 9, True), (3, 0, False)]
		self.assertEqual(sgpa(courses), 8.11)

	def test_sgpa_with_a_half_grade_point(self):
		self.assertEqual(sgpa([(3, 6.5, True), (2, 8, True), (4, 9, True)]), 7.94)  # 71.5/9

	def test_sgpa_is_zero_when_nothing_passed(self):
		self.assertEqual(sgpa([(3, 0, False)]), 0.0)
		self.assertEqual(sgpa([]), 0.0)

	def test_cgpa_pools_attempts_across_sessions(self):
		attempts = [("P", 4, 9, True), ("A", 3, 7, True), ("B", 2, 8, True), ("C", 3, 0, False)]
		self.assertEqual(cgpa(attempts), 8.11)  # (4*9 + 3*7 + 2*8) / 9 = 73/9

	def test_cgpa_counts_a_later_pass_in_place_of_an_earlier_one(self):
		attempts = [("A", 3, 5, True), ("B", 2, 8, True), ("A", 3, 9, True)]  # A re-attempted: 9 replaces 5
		self.assertEqual(cgpa(attempts), 8.6)  # (3*9 + 2*8) / 5 = 8.6

	def test_cgpa_ignores_a_failed_reattempt_of_a_passed_course(self):
		self.assertEqual(cgpa([("A", 3, 7, True), ("A", 3, 0, False)]), 7.0)

	def test_rounding_is_half_up_to_two_places(self):
		self.assertEqual(round_half_up(8.125, 2), 8.13)
		self.assertEqual(round_half_up(8.124, 2), 8.12)
