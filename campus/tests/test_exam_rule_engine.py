"""M06-05, M05-03 unit tests of the exam rule engine (P2-T12) on the seeded AU-R2021, R2022 and R2026 values:
the per-regulation fixture table, attempts, Box-Cox relative grading, GPA exclusions and classification."""

import random

from frappe.tests import UnitTestCase

from campus.examinations import seed
from campus.examinations.rules import (
	attempt_cia,
	attempt_number,
	boxcox_lambda,
	boxcox_log_likelihood,
	cgpa,
	classify,
	counts_in_gpa,
	course_outcome,
	grade,
	graded_mark,
	grading_method,
	internal_pass,
	may_attempt,
	pass_basis,
	pass_status,
	passed_at_first_appearance,
	percentage,
	relative_grade,
	relative_grade_bands,
	sgpa,
)

GRADES = {code: seed.rows(seed.GRADE_FIELDS, values) for code, values in seed.GRADES.items()}
RULES = {
	code: {row["course_type"]: row for row in seed.rows(seed.EXAM_RULE_FIELDS, values)}
	for code, values in seed.EXAM_RULES.items()
}
CLASSES = {code: seed.rows(seed.CLASS_FIELDS, values) for code, values in seed.CLASSES.items()}


def outcome(code, course_type, cia, ese, attempt=1):
	"""(result, letter, grade point) of one course under the seeded rules of regulation `code`."""
	return course_outcome(cia, ese, RULES[code][course_type], GRADES[code], attempt)


# regulation, course type, CIA, ESE, attempt, expected (result, letter, grade point); comments give ESE % / total %
FIXTURES = [
	# AU-R2021: Theory 40:60, Lab 60:40, Project 40:60; ESE >= 45 and total >= 50 on every attempt
	("AU-R2021", "Theory", 36, 54, 1, ("Pass", "A+", 9)),  # 90 / 90
	("AU-R2021", "Theory", 38, 57, 1, ("Pass", "O", 10)),  # 95 / 95
	("AU-R2021", "Theory", 20, 27, 1, ("Fail", "U", 0)),  # 45 / 47
	("AU-R2021", "Theory", 30, 26, 1, ("Fail", "U", 0)),  # 43.3 / 56
	("AU-R2021", "Theory", 23, 27, 1, ("Pass", "C", 5)),  # 45 / 50
	("AU-R2021", "Theory", 34, 28, 1, ("Pass", "B+", 7)),  # 46.7 / 62
	("AU-R2021", "Theory", 30, 28, 1, ("Pass", "B", 6)),  # 46.7 / 58
	("AU-R2021", "Theory", 18, 30, 3, ("Fail", "U", 0)),  # 50 / 48: no ESE-alone rule in R2021
	("AU-R2021", "Lab", 50, 30, 1, ("Pass", "A", 8)),  # 75 / 80
	("AU-R2021", "Lab", 30, 17, 1, ("Fail", "U", 0)),  # 42.5 / 47
	("AU-R2021", "Project", 30, 40, 1, ("Pass", "B+", 7)),  # 66.7 / 70
	("AU-R2021", "Project", 40, 26, 1, ("Fail", "U", 0)),  # 43.3 / 66
	# R2022: Theory 40:60, Theory with Lab 50:50, Lab and Project 60:40; from attempt 3 the ESE alone at 50% passes
	("R2022", "Theory", 28, 35, 1, ("Pass", "B+", 7)),  # 58.3 / 63
	("R2022", "Theory", 33.6, 26.4, 1, ("Fail", "U", 0)),  # 44 / 60
	("R2022", "Theory", 33, 27, 1, ("Pass", "B", 6)),  # 45 / 60
	("R2022", "Theory", 38, 57, 1, ("Pass", "O", 10)),  # 95 / 95
	("R2022", "Theory", 18, 30, 3, ("Pass", "C", 5)),  # AC2: 50 / 48 on the 3rd attempt, graded on the better: ESE 50
	("R2022", "Theory", 18, 30, 1, ("Fail", "U", 0)),  # 50 / 48 on the 1st attempt
	("R2022", "Theory", 18, 30, 2, ("Fail", "U", 0)),  # 50 / 48 on the 2nd attempt
	("R2022", "Theory", 26.8, 28.2, 1, ("Pass", "C", 5)),  # AC2: 47 / 55 on the 1st attempt
	("R2022", "Theory", 26.8, 28.2, 3, ("Pass", "C", 5)),  # 47 / 55 still passes on the total from attempt 3
	("R2022", "Theory", 10, 29.4, 3, ("Fail", "U", 0)),  # 49 / 39.4 on the 3rd attempt
	("R2022", "Theory", 0, 45, 4, ("Pass", "A", 8)),  # 75 / 45 on the 4th attempt: the better of the two is the ESE 75
	("R2022", "Theory", 40, 30, 3, ("Pass", "B+", 7)),  # 50 / 70 on the 3rd attempt: the better of the two is the total 70
	("R2022", "Theory", 10, 45, 3, ("Pass", "A", 8)),  # 75 / 55 on the 3rd attempt: the ESE 75 beats the total 55
	("R2022", "Theory", 10, 45, 2, ("Pass", "C", 5)),  # 75 / 55 on the 2nd attempt: no ESE-alone rule yet, total 55
	("R2022", "Theory with Lab", 45, 45, 1, ("Pass", "A+", 9)),  # 90 / 90
	("R2022", "Theory with Lab", 25, 23, 1, ("Fail", "U", 0)),  # 46 / 48
	("R2022", "Lab", 45, 30, 1, ("Pass", "A", 8)),  # 75 / 75
	("R2022", "Lab", 58, 37, 1, ("Pass", "O", 10)),  # 92.5 / 95
	("R2022", "Lab", 10, 20, 3, ("Pass", "C", 5)),  # 50 / 30 on the 3rd attempt
	("R2022", "Project", 50, 20, 1, ("Pass", "B+", 7)),  # 50 / 70
	("R2022", "Project", 40, 17, 1, ("Fail", "U", 0)),  # 42.5 / 57
	# R2026: same pass rule on every attempt; S 10, B 6.5 (61-65), C+ 6 (56-60)
	("R2026", "Theory", 28, 35, 1, ("Pass", "B", 6.5)),  # 58.3 / 63
	("R2026", "Theory", 33, 27, 1, ("Pass", "C+", 6)),  # 45 / 60
	("R2026", "Theory", 38, 57, 1, ("Pass", "S", 10)),  # 95 / 95
	("R2026", "Theory", 30, 36, 1, ("Pass", "B+", 7)),  # 60 / 66
	("R2026", "Theory", 18, 30, 3, ("Fail", "U", 0)),  # 50 / 48: no ESE-alone rule in R2026
	("R2026", "Theory", 26.8, 28.2, 1, ("Pass", "C", 5)),  # 47 / 55
	("R2026", "Theory", 40, 26, 1, ("Fail", "U", 0)),  # 43.3 / 66
	("R2026", "Theory", 20, 30, 1, ("Pass", "C", 5)),  # 50 / 50
	("R2026", "Theory with Lab", 30, 26, 1, ("Pass", "C+", 6)),  # 52 / 56
	("R2026", "Lab", 50, 30, 1, ("Pass", "A", 8)),  # 75 / 80
	("R2026", "Lab", 58, 37, 1, ("Pass", "S", 10)),  # 92.5 / 95
	("R2026", "Project", 45, 20, 1, ("Pass", "B", 6.5)),  # 50 / 65
	("R2026", "Project", 55, 17, 1, ("Fail", "U", 0)),  # 42.5 / 72
]  # fmt: skip


class TestFixtureTable(UnitTestCase):
	def test_fixture_table_has_40_cases_across_the_three_regulations(self):
		self.assertGreaterEqual(len(FIXTURES), 40)
		self.assertEqual({case[0] for case in FIXTURES}, set(seed.GRADES))

	def test_every_fixture_gives_the_expected_result_and_grade(self):
		for code, course_type, cia, ese, attempt, expected in FIXTURES:
			with self.subTest(code=code, course_type=course_type, cia=cia, ese=ese, attempt=attempt):
				self.assertEqual(outcome(code, course_type, cia, ese, attempt), expected)

	def test_r2022_top_letter_is_o_and_r2026_is_s(self):
		self.assertEqual(grade(95, GRADES["R2022"]), ("O", 10))
		self.assertEqual(grade(95, GRADES["R2026"]), ("S", 10))


class TestAttempts(UnitTestCase):
	def test_ese_alone_rule_only_from_its_attempt(self):
		args = (18, 30, 40, 60, 45, 50)
		self.assertEqual(pass_basis(*args, attempt=3, ese_only_from_attempt=3, ese_only_min_pct=50), "ese")
		self.assertIsNone(pass_basis(*args, attempt=2, ese_only_from_attempt=3, ese_only_min_pct=50))
		self.assertIsNone(pass_basis(*args, attempt=5))  # no attempt rule
		self.assertEqual(
			pass_basis(23, 27, 40, 60, 45, 50, attempt=3, ese_only_from_attempt=3, ese_only_min_pct=50),
			"total",
		)

	def test_pass_status_keeps_the_plain_signature(self):
		self.assertTrue(pass_status(23, 27, 40, 60, 45, 50))
		self.assertTrue(
			pass_status(18, 30, 40, 60, 45, 50, attempt=3, ese_only_from_attempt=3, ese_only_min_pct=50)
		)

	def test_graded_mark_is_the_better_of_total_and_ese_once_ese_alone_applies(self):
		self.assertAlmostEqual(graded_mark(18, 30, 40, 60, ese_alone_applies=True), 50)
		self.assertAlmostEqual(graded_mark(40, 30, 40, 60, ese_alone_applies=True), 70)
		self.assertAlmostEqual(graded_mark(18, 30, 40, 60), 48)
		self.assertAlmostEqual(graded_mark(0, 45, 40, 60), 45)

	def test_higher_cia_never_gives_a_lower_grade(self):
		# R2022 theory, ESE 45/60 = 75% on the 3rd attempt: CIA 0 passes on the ESE alone (total 45) and CIA 10
		# passes on the total (55); both are graded on the better mark, the ESE 75 (A)
		self.assertEqual(outcome("R2022", "Theory", 0, 45, 3), ("Pass", "A", 8))
		self.assertEqual(outcome("R2022", "Theory", 10, 45, 3), ("Pass", "A", 8))
		rule, grades = RULES["R2022"]["Theory"], GRADES["R2022"]
		for attempt in (1, 3):
			points = [course_outcome(cia, 45, rule, grades, attempt)[2] for cia in range(0, 41)]
			self.assertEqual(points, sorted(points), attempt)

	def test_attempt_number_counts_fails_and_absences_only_when_ruled(self):
		self.assertEqual(attempt_number([], True), 1)
		self.assertEqual(attempt_number(["Fail", "AB"], True), 3)
		self.assertEqual(attempt_number(["Fail", "AB"], False), 2)

	def test_withdrawal_and_shortage_are_not_attempts(self):
		self.assertEqual(attempt_number(["WD", "SA", "Fail"], True), 2)

	def test_third_attempt_after_an_absence_gets_the_r2022_rule(self):
		attempt = attempt_number(["Fail", "AB"], seed.ATTEMPT_RULES["R2022"]["absent_counts_as_attempt"])
		self.assertEqual(outcome("R2022", "Theory", 18, 30, attempt), ("Pass", "C", 5))

	def test_max_attempts(self):
		self.assertTrue(may_attempt(9, 0))
		self.assertTrue(may_attempt(4, 4))
		self.assertFalse(may_attempt(5, 4))

	def test_cia_carry_forward_keeps_the_first_attempt(self):
		self.assertEqual(attempt_cia([32, 20, 25], carry_forward=True), 32)
		self.assertEqual(attempt_cia([32, 20, 25], carry_forward=False), 25)
		self.assertEqual(seed.ATTEMPT_RULES["R2022"]["cia_carry_forward"], 1)

	def test_internal_only_course_passes_at_its_pct_of_cia(self):
		self.assertTrue(internal_pass(50, 100, 50))
		self.assertFalse(internal_pass(49.5, 100, 50))

	def test_revaluation_is_for_theory_types_only(self):
		eligible = {
			code: {t for t, row in rules.items() if row["revaluation_allowed"]}
			for code, rules in RULES.items()
		}
		self.assertEqual(eligible["AU-R2021"], {"Theory"})
		self.assertEqual(eligible["R2022"], {"Theory", "Theory with Lab"})
		self.assertEqual(eligible["R2026"], {"Theory", "Theory with Lab"})


def cohort(seed_value, size=40):
	rng = random.Random(seed_value)
	return [round(rng.uniform(50, 99), 1) for _ in range(size)]


class TestRelativeGrading(UnitTestCase):
	def test_relative_only_above_the_minimum_cohort(self):
		self.assertEqual(grading_method("Theory", "Relative Box-Cox", 31, 30), "Relative Box-Cox")
		self.assertEqual(grading_method("Theory", "Relative Box-Cox", 30, 30), "Absolute")
		self.assertEqual(grading_method("Theory with Lab", "Relative Box-Cox", 45, 30), "Relative Box-Cox")

	def test_labs_and_projects_are_always_absolute(self):
		self.assertEqual(grading_method("Lab", "Relative Box-Cox", 100, 30), "Absolute")
		self.assertEqual(grading_method("Project", "Relative Box-Cox", 100, 30), "Absolute")

	def test_no_method_row_is_absolute_and_online_uses_its_table(self):
		self.assertEqual(grading_method("Theory", None, 100, 0), "Absolute")
		self.assertEqual(grading_method("Online", "Online Table", 3, 0), "Online Table")

	def test_bands_are_deterministic_for_the_same_input_in_any_order(self):
		marks = cohort(7)
		bands = relative_grade_bands(marks, GRADES["R2022"])
		shuffled = list(marks)
		random.Random(1).shuffle(shuffled)
		self.assertEqual(relative_grade_bands(shuffled, GRADES["R2022"]), bands)
		self.assertEqual(relative_grade_bands(list(marks), GRADES["R2022"]), bands)

	def test_bands_fall_from_o_to_c_and_c_starts_at_the_pass_mark(self):
		bands = relative_grade_bands(cohort(11), GRADES["R2022"])
		self.assertEqual([b["letter"] for b in bands], ["O", "A+", "A", "B+", "B", "C"])
		minimums = [b["min_mark"] for b in bands]
		self.assertEqual(minimums, sorted(minimums, reverse=True))
		self.assertEqual(minimums[-1], 50)

	def test_lambda_maximises_the_log_likelihood(self):
		marks = sorted(cohort(3))
		lam = boxcox_lambda(marks)
		best = boxcox_log_likelihood(marks, lam)
		for step in (-0.05, 0.05):
			self.assertGreater(best, boxcox_log_likelihood(marks, lam + step))

	def test_a_symmetric_cohort_gets_bands_near_mean_plus_k_sd(self):
		# mean 69, SD 5.74: linear cut-offs 77.6 / 71.9 / 66.1 / 63.3 / 60.4; the MLE lambda (0.74) shifts them a little
		marks = [60, 62, 64, 66, 68, 70, 72, 74, 76, 78] * 4
		self.assertEqual(boxcox_lambda(marks), 0.740126)  # a 0.001 grid search over -5..5 also peaks at 0.74
		bands = relative_grade_bands(marks, GRADES["R2022"])
		self.assertEqual([b["min_mark"] for b in bands], [77.7, 71.83, 66.08, 63.25, 60.46, 50])
		self.assertEqual(relative_grade(69, bands), ("A", 8))
		self.assertEqual(relative_grade(78, bands), ("O", 10))
		self.assertEqual(relative_grade(61, bands), ("B", 6))
		self.assertEqual(relative_grade(60, bands), ("C", 5))

	def test_equal_marks_cannot_be_graded_relatively(self):
		with self.assertRaises(ValueError):
			relative_grade_bands([70] * 35, GRADES["R2022"])

	def test_a_degenerate_cohort_falls_back_to_absolute(self):
		relative = ("Theory", "Relative Box-Cox", 35, 30)
		self.assertEqual(grading_method(*relative, totals=[70] * 35), "Absolute")  # identical marks
		self.assertEqual(
			grading_method(*relative, totals=[60, 80] * 17 + [60]), "Absolute"
		)  # two distinct values
		self.assertEqual(
			grading_method(*relative, totals=[99.9] * 32 + [99.8, 50, 51]), "Absolute"
		)  # lambda 5.0, the bound
		self.assertEqual(grading_method(*relative, totals=[50.1] * 33 + [99, 98]), "Absolute")  # lambda -5.0
		self.assertEqual(grading_method(*relative, totals=cohort(7, 35)), "Relative Box-Cox")
		self.assertEqual(grading_method(*relative), "Relative Box-Cox")  # no marks given: cohort size only


GPA_COURSES = [
	{"credits": 3, "grade_point": 8, "passed": True, "category": "PCC"},
	{"credits": 4, "grade_point": 7, "passed": True, "category": "PCC"},
	{"credits": 3, "grade_point": 0, "passed": False, "category": "PCC"},  # U
	{"credits": 2, "grade_point": 10, "passed": True, "category": "MC"},  # mandatory course
	{
		"credits": 3,
		"grade_point": 10,
		"passed": True,
		"category": "PEC",
		"additional": 1,
	},  # Honours course
]


class TestGpaExclusions(UnitTestCase):
	def gpa_of(self, additional_counts):
		counted = [
			c for c in GPA_COURSES if counts_in_gpa(c, seed.GPA_EXCLUDED_CATEGORIES, additional_counts)
		]
		return sgpa([(c["credits"], c["grade_point"], c["passed"]) for c in counted])

	def test_sgpa_excludes_u_mandatory_and_additional_courses(self):
		self.assertEqual(self.gpa_of(False), 7.43)  # (3*8 + 4*7) / 7 = 52/7

	def test_additional_courses_count_once_honours_is_completed(self):
		self.assertEqual(self.gpa_of(True), 8.2)  # (24 + 28 + 30) / 10

	def test_cgpa_excludes_the_same_and_converts_to_a_percentage(self):
		attempts = [
			(c["category"] + str(i), c["credits"], c["grade_point"], c["passed"])
			for i, c in enumerate(GPA_COURSES)
			if counts_in_gpa(c, seed.GPA_EXCLUDED_CATEGORIES)
		]
		value = cgpa(attempts)
		self.assertEqual(value, 7.43)
		self.assertEqual(percentage(value), 74.3)

	def test_seeded_regulations_exclude_mandatory_courses(self):
		self.assertIn("MC", seed.GPA_EXCLUDED_CATEGORIES)
		self.assertEqual(seed.COUNT_ADDITIONAL_WITH_HONOURS["R2022"], 1)


class TestClassification(UnitTestCase):
	def test_distinction_with_a_withdrawal_keeps_first_appearance(self):
		first = passed_at_first_appearance({"MA101": ["WD", "Pass"], "PH101": ["Pass"]})
		self.assertTrue(first)
		self.assertEqual(
			classify(8.7, CLASSES["R2022"], first_appearance=first, years_taken=4),
			("First Class with Distinction", "Regular"),
		)

	def test_an_arrear_drops_distinction_to_first_class(self):
		first = passed_at_first_appearance({"MA101": ["Fail", "Pass"], "PH101": ["Pass"]})
		self.assertFalse(first)
		self.assertEqual(
			classify(8.7, CLASSES["R2022"], first_appearance=first, years_taken=4), ("First Class", "Regular")
		)

	def test_shortage_or_absence_is_not_a_first_appearance(self):
		self.assertFalse(passed_at_first_appearance({"MA101": ["SA", "Pass"]}))
		self.assertFalse(passed_at_first_appearance({"MA101": ["AB", "Pass"]}))

	def test_break_of_study_counts_within_r2022_five_years(self):
		self.assertEqual(
			classify(8.7, CLASSES["R2022"], years_taken=5, break_years=1)[0], "First Class with Distinction"
		)
		self.assertEqual(classify(8.7, CLASSES["R2022"], years_taken=6, break_years=1)[0], "Second Class")

	def test_break_of_study_excluded_when_the_rule_says_so(self):
		classes = [{**row, "break_of_study_included": 0} for row in CLASSES["R2022"]]
		self.assertEqual(
			classify(8.7, classes, years_taken=6, break_years=1)[0], "First Class with Distinction"
		)

	def test_first_and_second_class_thresholds(self):
		for code in seed.CLASSES:
			with self.subTest(code=code):
				self.assertEqual(
					classify(6.5, CLASSES[code], first_appearance=False, years_taken=4)[0], "First Class"
				)
				self.assertEqual(classify(6.49, CLASSES[code], years_taken=4)[0], "Second Class")
				self.assertEqual(
					classify(8.5, CLASSES[code], years_taken=4)[0], "First Class with Distinction"
				)

	def test_honours_variant_needs_7_5_for_first_class_and_falls_back_to_regular(self):
		self.assertEqual(
			classify(7.6, CLASSES["R2022"], "Honours", first_appearance=False, years_taken=4),
			("First Class", "Honours"),
		)
		self.assertEqual(
			classify(7.0, CLASSES["R2022"], "Honours", first_appearance=False, years_taken=4),
			("First Class", "Regular"),
		)
		self.assertEqual(
			classify(8.9, CLASSES["R2026"], "Honours", years_taken=4),
			("First Class with Distinction", "Honours"),
		)

	def test_lateral_entry_has_four_years_for_distinction_in_r2022(self):
		self.assertEqual(
			classify(8.7, CLASSES["R2022"], years_taken=4, entry_type="Lateral")[0],
			"First Class with Distinction",
		)
		self.assertEqual(
			classify(8.7, CLASSES["R2022"], years_taken=5, entry_type="Lateral")[0], "First Class"
		)
		self.assertEqual(
			classify(8.7, CLASSES["R2022"], years_taken=5, entry_type="Regular")[0],
			"First Class with Distinction",
		)
		self.assertEqual(
			classify(8.7, CLASSES["R2022"], "Honours", years_taken=5, entry_type="Lateral"),
			("First Class", "Honours"),
		)

	def test_no_matching_row_is_none(self):
		self.assertIsNone(classify(9, [CLASSES["R2022"][2]], first_appearance=False))
