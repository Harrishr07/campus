"""P3-T10 unit tests (M03-03): the attainment maths with fixture tables - a student's CO score per tool, the share of
students at the threshold, level bands, the CIA / ESE direct split, direct + indirect, PO = sum(CO final x correlation)
/ sum(correlation), targets, and the valuation rounds whose question marks count."""

from frappe.tests import UnitTestCase

from campus.curriculum import attainment_rules as rules
from campus.examinations import valuation_rules as vr

SXCCE = rules.Policy(
	direct_weight=80, indirect_weight=20, cia_weight=40, ese_weight=60, student_threshold=60,
	bands=((1, 40), (2, 50), (3, 60)), target_level=2,
)  # fmt: skip


class TestStudentScores(UnitTestCase):
	def test_a_students_co_score_adds_the_questions_tagged_with_it(self):
		rows = [
			{"student": "s1", "marks": 7, "max_marks": 10}, {"student": "s1", "marks": 5, "max_marks": 10},
			{"student": "s2", "marks": 3, "max_marks": 10},
		]  # fmt: skip
		self.assertEqual(rules.student_scores(rows), {"s1": (12, 20), "s2": (3, 10)})

	def test_an_absent_question_counts_neither_marks_nor_maximum(self):
		rows = [
			{"student": "s1", "marks": 6, "max_marks": 10}, {"student": "s1", "marks": 0, "max_marks": 10, "absent": 1},
			{"student": "s2", "marks": 0, "max_marks": 10, "absent": 1},
		]  # fmt: skip
		self.assertEqual(rules.student_scores(rows), {"s1": (6, 10)})  # s2 sat none of the CO's questions


class TestToolAttainment(UnitTestCase):
	def test_the_share_of_students_at_or_above_the_threshold(self):
		scores = {"a": (6, 10), "b": (5.9, 10), "c": (12, 20), "d": (20, 20)}
		self.assertEqual(rules.tool_attainment(scores, 60), (4, 3, 75.0))  # 60 % exactly attains

	def test_no_student_gives_no_figure(self):
		self.assertEqual(rules.tool_attainment({}, 60), (0, 0, None))

	def test_the_share_is_exact_and_banded_before_rounding(self):
		percent = rules.tool_attainment({"a": (9, 10), "b": (1, 10), "c": (1, 10)}, 60)[2]
		self.assertAlmostEqual(percent, 100 / 3, places=9)
		self.assertEqual(rules.rounded(percent), 33.33)
		self.assertEqual(rules.level_for(59.996, SXCCE.bands), 2)  # 60.00 once rounded, but not L3
		self.assertEqual(rules.rounded(59.996), 60)


class TestLevels(UnitTestCase):
	def test_the_highest_band_reached(self):
		bands = SXCCE.bands
		self.assertEqual(rules.level_for(60, bands), 3)
		self.assertEqual(rules.level_for(59.99, bands), 2)
		self.assertEqual(rules.level_for(50, bands), 2)
		self.assertEqual(rules.level_for(44.44, bands), 1)
		self.assertEqual(rules.level_for(39.99, bands), 0)

	def test_no_percent_no_level(self):
		self.assertIsNone(rules.level_for(None, SXCCE.bands))

	def test_bands_in_any_order(self):
		self.assertEqual(rules.level_for(55, ((3, 60), (1, 40), (2, 50))), 2)

	def test_top_level_is_the_highest_band(self):
		self.assertEqual(rules.top_level(SXCCE.bands), 3)

	def test_indirect_level_scales_the_survey_mean_to_the_top_level(self):
		self.assertEqual(rules.indirect_level(4.0, 5, 3), 2.4)
		self.assertEqual(rules.indirect_level(3.6, 5, 3), 2.16)
		self.assertEqual(rules.indirect_level(3, 4, 3), 2.25)  # a 1-4 scale from the policy
		self.assertIsNone(rules.indirect_level(None, 5, 3))
		self.assertEqual(rules.survey_percent(3.6, 5), 72)


class TestWeighted(UnitTestCase):
	def test_weights_split_the_parts(self):
		self.assertEqual(rules.weighted([(3, 40), (2, 60)]), 2.4)

	def test_a_missing_part_leaves_the_others_on_their_own_weights(self):
		self.assertEqual(rules.weighted([(None, 40), (2, 60)]), 2)

	def test_a_zero_level_is_a_level_not_a_gap(self):
		self.assertEqual(rules.weighted([(0, 40), (2, 60)]), 1.2)

	def test_nothing_to_weigh(self):
		self.assertIsNone(rules.weighted([(None, 40), (None, 60)]))
		self.assertIsNone(rules.weighted([(2, 0)]))


class TestCOResult(UnitTestCase):
	"""The fixture course of test_attainment under the SXCCE policy (80/20; 60 ESE + 40 CIA; 60 %; 40/50/60)."""

	def test_co1_both_tools_and_the_survey(self):
		result = rules.co_result(cia=(10, 7, 70.0), ese=(9, 5, 55.56), indirect_average=4.0, policy=SXCCE)
		self.assertEqual((result.cia_level, result.ese_level, result.direct_level), (3, 2, 2.4))
		self.assertEqual((result.indirect_level, result.final_level, result.target_met), (2.4, 2.4, 1))

	def test_co2_misses_the_target(self):
		result = rules.co_result(cia=(10, 6, 60.0), ese=(9, 4, 44.44), indirect_average=3.6, policy=SXCCE)
		self.assertEqual((result.direct_level, result.indirect_level, result.final_level), (1.8, 2.16, 1.87))
		self.assertEqual((result.target_met, result.gap), (0, 0.13))

	def test_without_a_survey_score_the_final_is_the_direct(self):
		result = rules.co_result(cia=(9, 3, 33.33), ese=(9, 5, 55.56), indirect_average=None, policy=SXCCE)
		self.assertEqual((result.cia_level, result.direct_level, result.final_level), (0, 1.2, 1.2))
		self.assertIn(rules.NO_INDIRECT, result.notes)

	def test_a_co_without_cia_questions_is_direct_from_the_ese(self):
		result = rules.co_result(cia=(0, 0, None), ese=(9, 5, 55.56), indirect_average=None, policy=SXCCE)
		self.assertEqual((result.cia_level, result.direct_level), (None, 2))
		self.assertIn(rules.NO_CIA, result.notes)

	def test_a_co_assessed_nowhere_has_no_level(self):
		result = rules.co_result(cia=(0, 0, None), ese=(0, 0, None), indirect_average=4.5, policy=SXCCE)
		self.assertEqual((result.direct_level, result.final_level, result.target_met), (None, None, 0))
		self.assertIsNone(result.gap)

	def test_another_policy_gives_other_levels(self):
		other = rules.Policy(50, 50, 50, 50, 50, ((1, 30), (2, 40), (3, 50)), 2)
		result = rules.co_result(cia=(10, 6, 60.0), ese=(9, 4, 44.44), indirect_average=3.6, policy=other)
		self.assertEqual((result.cia_level, result.ese_level, result.direct_level, result.final_level), (3, 2, 2.5, 2.33))


class TestPOAttainment(UnitTestCase):
	def test_sum_of_co_final_times_correlation_over_sum_of_correlation(self):
		self.assertEqual(rules.po_direct([(2.4, 3), (1.87, 2)]), 2.19)  # 10.94 / 5
		self.assertEqual(rules.po_direct([(1.87, 3), (1.2, 1)]), 1.7)  # 6.81 / 4

	def test_unassessed_cos_and_zero_cells_are_left_out(self):
		self.assertEqual(rules.po_direct([(1.2, 2), (None, 3), (3, 0)]), 1.2)

	def test_a_course_in_several_sections_is_one_student_weighted_final(self):
		self.assertEqual(rules.combine_sections([(2.4, 10), (3, 30)]), 2.85)  # (24 + 90) / 40
		self.assertEqual(rules.combine_sections([(1.8, 60), (1.8, 60), (1.8, 60)]), 1.8)  # 3 sections weigh as one course
		self.assertEqual(rules.combine_sections([(2, 10), (None, 30), (3, 0)]), 2)
		self.assertIsNone(rules.combine_sections([]))

	def test_a_po_no_co_maps_to_has_no_level(self):
		self.assertIsNone(rules.po_direct([]))

	def test_po_final_weighs_in_the_exit_survey(self):
		result = rules.po_result(direct=2.19, indirect_average=4.4, scale=5, top=3, indirect_weight=20, target_level=2)
		self.assertEqual((result.indirect_level, result.final_level, result.target_met), (2.64, 2.28, 1))

	def test_po_final_without_the_survey_is_the_direct(self):
		result = rules.po_result(direct=1.7, indirect_average=None, scale=5, top=3, indirect_weight=20, target_level=2)
		self.assertEqual((result.final_level, result.target_met, result.gap), (1.7, 0, 0.3))

	def test_an_unmapped_po(self):
		result = rules.po_result(direct=None, indirect_average=4.4, scale=5, top=3, indirect_weight=20, target_level=2)
		self.assertEqual((result.final_level, result.target_met), (None, 0))
		self.assertIn(rules.NOT_MAPPED, result.notes)


class TestDecidingRounds(UnitTestCase):
	"""The rounds whose average is the final ESE mark: their question marks are the ones attainment counts."""

	def test_two_valuations(self):
		self.assertEqual(vr.deciding_rounds({2: 44, 1: 41}, vr.AVERAGE_OF_CLOSEST_TWO), (1, 2))

	def test_closest_pair_of_three(self):
		self.assertEqual(vr.deciding_rounds({1: 0, 2: 31, 3: 29}, vr.AVERAGE_OF_CLOSEST_TWO), (2, 3))
		self.assertEqual(vr.deciding_rounds({1: 40, 2: 60, 3: 80}, vr.AVERAGE_OF_CLOSEST_TWO), (2, 3))  # tie: higher pair

	def test_third_and_nearer(self):
		self.assertEqual(vr.deciding_rounds({1: 20, 2: 30, 3: 60}, vr.AVERAGE_OF_THIRD_AND_NEARER), (2, 3))
		self.assertEqual(vr.deciding_rounds({1: 40, 2: 60, 3: 50}, vr.AVERAGE_OF_THIRD_AND_NEARER), (2, 3))  # tie: higher

	def test_final_mark_is_the_average_of_the_deciding_rounds(self):
		self.assertEqual(vr.final_mark({1: 0, 2: 31, 3: 29}, vr.AVERAGE_OF_CLOSEST_TWO), 30)
