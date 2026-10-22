"""M06-04 unit tests: third-valuation trigger, final ESE mark rules, bundle completeness and dummy-number draws."""

from frappe.tests import UnitTestCase

from campus.examinations import valuation_rules as vr

CLOSEST, THIRD_NEARER = vr.AVERAGE_OF_CLOSEST_TWO, vr.AVERAGE_OF_THIRD_AND_NEARER


class TestThirdValuationTrigger(UnitTestCase):
	def test_a_difference_above_the_threshold_needs_a_third_valuation(self):
		# ESE out of 60, threshold 15% = 9 marks: 40 vs 50 differ by 10 (16.67%)
		self.assertTrue(vr.needs_third_valuation(40, 50, 60, 15))
		self.assertTrue(vr.needs_third_valuation(50, 40, 60, 15))

	def test_a_difference_at_or_below_the_threshold_does_not(self):
		self.assertFalse(vr.needs_third_valuation(40, 49, 60, 15))  # exactly 15%: not above
		self.assertFalse(vr.needs_third_valuation(40, 48, 60, 15))
		self.assertFalse(vr.needs_third_valuation(45, 45, 60, 15))

	def test_the_threshold_is_a_share_of_the_ese_maximum(self):
		# 10 marks is 10% of 100, under a 15% threshold; but 25% of 40
		self.assertFalse(vr.needs_third_valuation(40, 50, 100, 15))
		self.assertTrue(vr.needs_third_valuation(20, 30, 40, 15))


class TestFinalMark(UnitTestCase):
	def test_two_valuations_average_rounded_half_up(self):
		self.assertEqual(vr.final_mark({1: 41, 2: 44}, CLOSEST), 43)  # 42.5 -> 43
		self.assertEqual(vr.final_mark({1: 40, 2: 48}, CLOSEST), 44)
		self.assertEqual(vr.final_mark({1: 40, 2: 47}, THIRD_NEARER), 44)  # 43.5 -> 44: no third, same rule

	def test_closest_two_of_three(self):
		# pairs: (40,50)=10, (40,47)=7, (50,47)=3 -> (50+47)/2 = 48.5 -> 49
		self.assertEqual(vr.final_mark({1: 40, 2: 50, 3: 47}, CLOSEST), 49)
		# (20,30)=10, (20,60)=40, (30,60)=30 -> (20+30)/2 = 25
		self.assertEqual(vr.final_mark({1: 20, 2: 30, 3: 60}, CLOSEST), 25)

	def test_a_tie_between_pairs_takes_the_higher_pair(self):
		# (40,60)=20 and (60,80)=20 tie -> (60+80)/2 = 70
		self.assertEqual(vr.final_mark({1: 40, 2: 60, 3: 80}, CLOSEST), 70)

	def test_third_and_nearer(self):
		# third 60, nearer of 20/30 is 30 -> (60+30)/2 = 45
		self.assertEqual(vr.final_mark({1: 20, 2: 30, 3: 60}, THIRD_NEARER), 45)
		# third 47: 50 is nearer than 40 -> 48.5 -> 49
		self.assertEqual(vr.final_mark({1: 40, 2: 50, 3: 47}, THIRD_NEARER), 49)
		# third 50 equidistant from 40 and 60 -> the higher, (50+60)/2 = 55
		self.assertEqual(vr.final_mark({1: 40, 2: 60, 3: 50}, THIRD_NEARER), 55)

	def test_fractions_are_kept_until_the_final_rounding(self):
		self.assertEqual(vr.final_mark({1: 40.5, 2: 41}, CLOSEST), 41)  # 40.75 -> 41
		self.assertEqual(vr.final_mark({1: 40.25, 2: 40.5}, CLOSEST), 40)  # 40.375 -> 40

	def test_one_valuation_or_an_unknown_rule_is_refused(self):
		with self.assertRaises(ValueError):
			vr.final_mark({1: 40}, CLOSEST)
		with self.assertRaises(ValueError):
			vr.final_mark({1: 40, 2: 44}, "Highest")


class TestBundleCompleteness(UnitTestCase):
	def test_missing_scripts_are_counted_against_the_expected_count(self):
		self.assertEqual(vr.missing_scripts(3, [1, 1, 1]), 0)
		self.assertEqual(vr.missing_scripts(3, [1, 0, 1]), 1)  # one listed but not received
		self.assertEqual(vr.missing_scripts(3, [1, 1]), 1)  # one never listed
		self.assertEqual(vr.missing_scripts(2, []), 2)


class TestDummyNumberDraw(UnitTestCase):
	def test_a_drawn_number_already_taken_is_drawn_again(self):
		draws = iter([5, 5, 7, 5, 9])
		taken = set()
		numbers = [vr.draw_unique(lambda: next(draws), taken) for _ in range(3)]
		self.assertEqual(numbers, [5, 7, 9])
		self.assertEqual(taken, {5, 7, 9})

	def test_dummy_numbers_have_a_fixed_width_and_are_not_sequential(self):
		numbers = vr.dummy_numbers(200, set())
		self.assertEqual(len(set(numbers)), 200)
		self.assertTrue(all(len(n) == vr.DUMMY_DIGITS and n.isdigit() and n[0] != "0" for n in numbers))
		ordered = sorted(int(n) for n in numbers)
		self.assertGreater(len({b - a for a, b in zip(ordered, ordered[1:])}), 1)  # not a series

	def test_draws_avoid_numbers_in_use(self):
		taken = {str(n) for n in range(10**7, 10**7 + 5)}
		self.assertTrue(set(vr.dummy_numbers(5, set(taken))).isdisjoint(taken))
