"""M06-05 unit tests of the Result Run's pure rules (P2-T19): combining CIA and ESE with moderation and grace,
CIA carried forward for arrears, grace allocation under the Exam Rule Set limits, the overall result and the
change log of a new result version."""

from frappe.tests import UnitTestCase

from campus.examinations.result_rules import (
	allocate_grace,
	arrear_cia,
	change_log,
	combined_ese,
	grace_needed,
	overall_result,
)

# R2022 theory: CIA 40 + ESE 60, ESE >= 45 %, total >= 50 %
THEORY = dict(cia_max=40, ese_max=60, ese_min_pct=45, total_min_pct=50)
GRACE = dict(grace_allowed=1, grace_max_per_course=5, grace_max_courses=2, grace_max_total=6)


class TestCombination(UnitTestCase):
	def test_moderation_and_grace_add_to_the_ese(self):
		self.assertEqual(combined_ese(30, 2, 1, 60), 33)

	def test_negative_moderation_lowers_the_ese(self):
		self.assertEqual(combined_ese(30, -3, 0, 60), 27)

	def test_the_ese_stays_inside_zero_and_its_maximum(self):
		self.assertEqual(combined_ese(58, 5, 0, 60), 60)
		self.assertEqual(combined_ese(2, -5, 0, 60), 0)


class TestCarryForward(UnitTestCase):
	def test_carry_forward_keeps_the_first_attempts_cia(self):
		self.assertEqual(arrear_cia([22, 30], 35, carry_forward=True), 22)

	def test_without_carry_forward_the_latest_cia_counts(self):
		self.assertEqual(arrear_cia([22, 30], 35, carry_forward=False), 35)

	def test_without_a_new_cia_the_latest_earlier_one_counts(self):
		self.assertEqual(arrear_cia([22, 30], None, carry_forward=False), 30)

	def test_a_first_attempt_has_only_the_current_cia(self):
		self.assertEqual(arrear_cia([], 18, carry_forward=True), 18)
		self.assertEqual(arrear_cia([], None, carry_forward=True), 0)


class TestGraceNeeded(UnitTestCase):
	def test_a_pass_needs_no_grace(self):
		self.assertEqual(grace_needed(28, 35, **THEORY), 0)

	def test_whole_marks_to_reach_the_ese_minimum(self):
		self.assertEqual(grace_needed(33.6, 26.4, **THEORY), 1)  # ESE 26.4 of 60: 27 is 45 %

	def test_whole_marks_to_reach_the_total_minimum(self):
		self.assertEqual(grace_needed(10, 37, **THEORY), 3)  # ESE passes; total 47 needs 50

	def test_the_larger_of_the_two_shortfalls(self):
		self.assertEqual(grace_needed(5, 24, **THEORY), 21)  # ESE needs 3, the total 21

	def test_exactly_on_the_boundary_needs_nothing(self):
		self.assertEqual(grace_needed(23, 27, **THEORY), 0)  # ESE 45 %, total 50 %
		self.assertEqual(grace_needed(22.5, 27, **THEORY), 1)  # total 49.5: half a mark short, one whole mark

	def test_none_when_even_the_full_ese_cannot_pass(self):
		self.assertIsNone(grace_needed(0, 10, cia_max=40, ese_max=60, ese_min_pct=45, total_min_pct=70))


class TestGraceAllocation(UnitTestCase):
	def test_not_allowed_gives_nothing(self):
		self.assertEqual(allocate_grace({"C1": 1}, {**GRACE, "grace_allowed": 0}), {})

	def test_within_the_per_course_limit(self):
		self.assertEqual(allocate_grace({"C1": 1, "C2": 6}, GRACE), {"C1": 1})

	def test_smallest_shortfall_first_up_to_the_course_count(self):
		self.assertEqual(allocate_grace({"C1": 3, "C2": 1, "C3": 2}, GRACE), {"C2": 1, "C3": 2})

	def test_the_total_budget_is_never_exceeded(self):
		self.assertEqual(allocate_grace({"C1": 4, "C2": 3}, GRACE), {"C2": 3})

	def test_zero_limits_mean_no_cap(self):
		rule = {**GRACE, "grace_max_courses": 0, "grace_max_total": 0}
		self.assertEqual(allocate_grace({"C1": 4, "C2": 3, "C3": 5}, rule), {"C1": 4, "C2": 3, "C3": 5})

	def test_ties_are_broken_by_course_for_a_stable_result(self):
		self.assertEqual(allocate_grace({"B": 2, "A": 2, "C": 2}, GRACE), {"A": 2, "B": 2})


class TestOverallResult(UnitTestCase):
	def test_every_course_passed(self):
		self.assertEqual(overall_result(["Pass", "Pass"]), "Pass")

	def test_any_other_outcome_is_a_reappearance(self):
		for outcome in ("Fail", "AB", "SA", "WD"):
			self.assertEqual(overall_result(["Pass", outcome]), "Reappear", outcome)

	def test_nothing_graded_has_no_result(self):
		self.assertEqual(overall_result([]), "")


class TestChangeLog(UnitTestCase):
	def summary(self, sgpa, cgpa, rows):
		return {"sgpa": sgpa, "cgpa": cgpa, "courses": [dict(course=c, grade=g, result=r, total=t) for c, g, r, t in rows]}

	def test_lists_changed_courses_and_gpas_only(self):
		old = self.summary(8.11, 8.38, [("TH", "B+", "Pass", 63), ("FA", "U", "Fail", 60)])
		new = self.summary(8.4, 8.52, [("TH", "B+", "Pass", 63), ("FA", "A", "Pass", 73.6)])
		self.assertEqual(
			change_log(old, new).splitlines(),
			["FA: U (Fail) -> A (Pass), total 60 -> 73.6", "SGPA: 8.11 -> 8.4", "CGPA: 8.38 -> 8.52"],
		)

	def test_added_and_removed_courses(self):
		old = self.summary(8, 8, [("TH", "A", "Pass", 75)])
		new = self.summary(8, 8, [("LB", "A", "Pass", 75)])
		self.assertEqual(change_log(old, new).splitlines(), ["LB: added, A (Pass)", "TH: removed, was A (Pass)"])

	def test_no_change_is_empty(self):
		same = self.summary(8, 8, [("TH", "A", "Pass", 75)])
		self.assertEqual(change_log(same, same), "")
