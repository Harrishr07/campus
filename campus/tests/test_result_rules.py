"""M06-05 unit tests of the Result Run's pure rules (P2-T19): combining CIA and ESE with moderation and grace,
CIA carried forward for arrears, grace allocation under the Exam Rule Set limits, the overall result and the
change log of a new result version."""

from frappe.tests import UnitTestCase

from campus.examinations.result_rules import (
	allocate_grace,
	arrear_cia,
	change_log,
	combined_ese,
	configuration_gaps,
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

	def test_the_ese_alone_basis_needs_less_from_its_attempt(self):
		# R2022, 3rd attempt: CIA 5 + ESE 28 needs 17 on the total basis, 2 to reach the ESE-alone 50 % (30 of 60)
		self.assertEqual(grace_needed(5, 28, **THEORY), 17)
		self.assertEqual(grace_needed(5, 28, **THEORY, ese_alone_min_pct=50), 2)

	def test_the_ese_alone_basis_can_rescue_an_otherwise_impossible_pass(self):
		self.assertIsNone(grace_needed(0, 40, cia_max=40, ese_max=60, ese_min_pct=45, total_min_pct=70))
		self.assertEqual(grace_needed(0, 40, cia_max=40, ese_max=60, ese_min_pct=45, total_min_pct=70, ese_alone_min_pct=70), 2)

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
	def summary(self, sgpa, cgpa, rows, arrears=0, classification=None):
		return {"sgpa": sgpa, "cgpa": cgpa, "arrear_count": arrears, "classification": classification,
			"courses": [dict(course=c, grade=g, result=r, total=t) for c, g, r, t in rows]}  # fmt: skip

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

	def test_arrears_and_classification_changes_are_listed(self):
		old = self.summary(8, 8, [("TH", "A", "Pass", 75)], arrears=1)
		new = self.summary(8, 8, [("TH", "A", "Pass", 75)], arrears=0, classification="First Class")
		self.assertEqual(change_log(old, new).splitlines(), ["Arrears: 1 -> 0", "Classification: - -> First Class"])

	def test_no_change_is_empty(self):
		same = self.summary(8, 8, [("TH", "A", "Pass", 75)])
		self.assertEqual(change_log(same, same), "")


class TestConfigurationGaps(UnitTestCase):
	"""M06-12 pre-validation of a Result Run: each offered course needs a course type its students' rule sets cover."""

	RULES = {"R2022": {"Theory", "Lab"}, "R2026": {"Theory"}}

	def course(self, exam_type="Theory", course_type="Theory", regulations=("R2022",), has_row=True):
		return {"label": "TH (G1)", "has_row": has_row, "exam_type": exam_type, "course_type": course_type, "regulations": set(regulations)}

	def gaps(self, *courses):
		return [label for label, _reason in configuration_gaps(courses, self.RULES)]

	def test_a_covered_course_has_no_gap(self):
		self.assertEqual(self.gaps(self.course()), [])

	def test_a_blank_course_type_is_a_gap(self):
		self.assertEqual(self.gaps(self.course(exam_type="", course_type="Theory")), ["TH (G1)"])
		self.assertEqual(self.gaps(self.course(exam_type=None, course_type="Theory")), ["TH (G1)"])

	def test_an_explicit_internal_only_course_needs_no_rule(self):
		self.assertEqual(self.gaps(self.course(exam_type="Internal Only", course_type=None, regulations=("R2030",))), [])

	def test_an_offering_without_a_curriculum_row_is_a_gap(self):
		self.assertEqual(self.gaps(self.course(has_row=False, exam_type=None, course_type=None)), ["TH (G1)"])

	def test_a_course_type_missing_from_a_students_rule_set_is_a_gap(self):
		found = configuration_gaps([self.course(exam_type="Practical", course_type="Lab", regulations=("R2022", "R2026"))], self.RULES)
		self.assertEqual(len(found), 1)
		self.assertIn("R2026", found[0][1])

	def test_a_regulation_without_a_rule_set_is_a_gap(self):
		found = configuration_gaps([self.course(regulations=("R2030",))], self.RULES)
		self.assertEqual(len(found), 1)
		self.assertIn("R2030", found[0][1])

	def test_a_student_without_a_regulation_is_a_gap(self):
		self.assertEqual(self.gaps(self.course(regulations=(None,))), ["TH (G1)"])

	def test_every_gap_of_a_course_is_listed(self):
		course = self.course(exam_type="Practical", course_type="Lab", regulations=("R2026", "R2030"))
		self.assertEqual(len(configuration_gaps([course], self.RULES)), 2)
