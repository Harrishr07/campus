"""M06-07, M05-03 unit tests (P2-T22): the consolidated record of a graduate (CGPA, % = CGPA x 10, arrears,
additional / Honours courses), its classification for the R2022 and R2026 seeds, progression outcomes and
export cell escaping. Pure: campus.examinations.graduation_rules, no database."""

from frappe.tests import UnitTestCase

from campus.examinations import graduation_rules as g
from campus.examinations.seed import CLASS_FIELDS, CLASSES, rows

R2022, R2026 = rows(CLASS_FIELDS, CLASSES["R2022"]), rows(CLASS_FIELDS, CLASSES["R2026"])
DISTINCTION, FIRST, SECOND = "First Class with Distinction", "First Class", "Second Class"


def attempt(course, grade_point, result="Pass", credits=3, in_gpa=1):
	return {
		"course": course,
		"credits": credits,
		"grade": "X",
		"grade_point": grade_point,
		"result": result,
		"in_gpa": in_gpa,
	}


# four 3-credit core courses: (9 + 9 + 8 + 9) / 4 = 8.75
STRONG = [attempt("C1", 9), attempt("C2", 9), attempt("C3", 8), attempt("C4", 9)]
# C3 failed first, cleared later at grade point 8: CGPA still 8.75, but not at the first appearance
CLEARED = [attempt("C1", 9), attempt("C2", 9), attempt("C3", 0, "Fail"), attempt("C4", 9), attempt("C3", 8)]
# (6 + 6 + 7 + 6) / 4 = 6.25
WEAK = [attempt("C1", 6), attempt("C2", 6), attempt("C3", 7), attempt("C4", 6)]


def classify(
	attempts,
	classes,
	kinds=None,
	years=4,
	break_years=0,
	entry_type="Regular",
	credits_needed=18,
	count_additional=1,
):
	record = g.consolidate(attempts, kinds or {}, credits_needed, count_additional)
	return g.classification(record, classes, years, break_years, entry_type)


class TestClassification(UnitTestCase):
	def test_ac1_distinction_first_class_with_cleared_arrears_and_second_class_in_r2022_and_r2026(self):
		for classes in (R2022, R2026):
			self.assertEqual(classify(STRONG, classes), (DISTINCTION, "Regular"))
			self.assertEqual(classify(CLEARED, classes), (FIRST, "Regular"))
			self.assertEqual(classify(WEAK, classes), (SECOND, "Regular"))

	def test_cgpa_percentage_and_cleared_arrears(self):
		record = g.consolidate(CLEARED, {}, 18, 1)
		self.assertEqual((record["cgpa"], record["percentage"], record["arrears"]), (8.75, 87.5, []))
		self.assertFalse(record["first_appearance"])
		self.assertEqual(
			[c["grade_point"] for c in record["core_courses"]], [9, 9, 8, 9]
		)  # the pass of C3 is listed

	def test_an_outstanding_arrear_is_listed_and_gets_no_class(self):
		record = g.consolidate([*STRONG[:3], attempt("C4", 0, "Fail")], {}, 18, 1)
		self.assertEqual(record["arrears"], ["C4"])
		self.assertIsNone(g.classification(record, R2022, 4, 0, "Regular"))

	def test_r2022_counts_the_break_of_study_in_its_five_years_r2026_has_no_limit(self):
		self.assertEqual(classify(STRONG, R2022, years=5, break_years=1), (DISTINCTION, "Regular"))
		self.assertEqual(
			classify(STRONG, R2022, years=6, break_years=1), (SECOND, "Regular")
		)  # break included
		self.assertEqual(classify(STRONG, R2026, years=6, break_years=1), (DISTINCTION, "Regular"))

	def test_r2022_lateral_entry_has_four_years_for_distinction(self):
		self.assertEqual(classify(STRONG, R2022, years=4, entry_type="Lateral"), (DISTINCTION, "Regular"))
		self.assertEqual(classify(STRONG, R2022, years=5, entry_type="Lateral"), (FIRST, "Regular"))

	def test_a_withdrawal_is_not_an_appearance(self):
		withdrawn = [attempt("C1", 0, "WD"), *STRONG]
		self.assertEqual(classify(withdrawn, R2022), (DISTINCTION, "Regular"))


HONOURS = {"H1": "Honours", "H2": "Honours", "A1": "Additional"}


def honours(points=(10, 10), credits=9):
	"""STRONG plus two Honours courses of `credits` each and one additional course at grade point 10."""
	return [
		*STRONG,
		attempt("H1", points[0], credits=credits),
		attempt("H2", points[1], credits=credits),
		attempt("A1", 10),
	]


class TestAdditionalAndHonours(UnitTestCase):
	def test_ac3_completed_honours_counts_the_additional_courses_in_the_cgpa(self):
		record = g.consolidate(honours(), HONOURS, 18, 1)
		self.assertEqual(record["variant"], "Honours")
		# (12 x 8.75 + 18 x 10 + 3 x 10) / 33 = 315 / 33 = 9.545 -> 9.55
		self.assertEqual(record["cgpa"], 9.55)
		self.assertEqual([c["course"] for c in record["core_courses"]], ["C1", "C2", "C3", "C4"])
		self.assertEqual([(c["course"], c["registration_type"], c["in_cgpa"]) for c in record["additional_courses"]],
			[("H1", "Honours", True), ("H2", "Honours", True), ("A1", "Additional", True)])  # fmt: skip
		self.assertEqual(g.classification(record, R2022, 4, 0, "Regular"), (DISTINCTION, "Honours"))

	def test_ac3_without_completed_honours_the_additional_courses_are_listed_but_not_in_the_cgpa(self):
		record = g.consolidate(honours(credits=6), HONOURS, 18, 1)  # 12 Honours credits of 18
		self.assertEqual((record["variant"], record["cgpa"]), ("Regular", 8.75))
		self.assertEqual([c["in_cgpa"] for c in record["additional_courses"]], [False, False, False])

	def test_ac3_a_regulation_that_never_counts_additional_courses(self):
		record = g.consolidate(honours(), HONOURS, 18, 0)  # AU-R2021: count_additional_with_honours off
		self.assertEqual((record["variant"], record["cgpa"]), ("Honours", 8.75))

	def test_a_failed_honours_course_is_no_arrear_and_no_credit(self):
		record = g.consolidate(
			[*STRONG, attempt("H1", 10, credits=9), attempt("H2", 0, "Fail", credits=9)], HONOURS, 18, 1
		)
		self.assertEqual((record["variant"], record["arrears"], record["cgpa"]), ("Regular", [], 8.75))

	def test_minor_and_no_specialisation_rule(self):
		minor = {"H1": "Minor", "H2": "Minor"}
		self.assertEqual(g.consolidate(honours(), minor, 18, 1)["variant"], "Minor")
		self.assertEqual(g.consolidate(honours(), HONOURS, 0, 1)["variant"], "Regular")  # 0: not offered

	def test_an_excluded_category_never_counts(self):
		record = g.consolidate([*STRONG, attempt("MC1", 0, in_gpa=0)], {}, 18, 1)
		self.assertEqual(record["cgpa"], 8.75)
		self.assertFalse(record["core_courses"][-1]["in_cgpa"])


class TestProgression(UnitTestCase):
	def test_outcomes(self):
		self.assertEqual(g.progression_outcome(3, 8.0, max_arrears=2, probation_below_cgpa=6), g.DETAIN)
		self.assertEqual(g.progression_outcome(2, 5.9, max_arrears=2, probation_below_cgpa=6), g.PROBATION)
		self.assertEqual(g.progression_outcome(2, 6.0, max_arrears=2, probation_below_cgpa=6), g.PROMOTE)
		self.assertEqual(
			g.progression_outcome(0, 3.0, max_arrears=0, probation_below_cgpa=0), g.PROMOTE
		)  # no probation
		self.assertEqual(g.progression_outcome(1, 9.0, max_arrears=0, probation_below_cgpa=0), g.DETAIN)

	def test_no_cgpa_yet_is_no_probation(self):
		self.assertEqual(g.progression_outcome(0, 0, max_arrears=2, probation_below_cgpa=6), g.PROMOTE)


class TestExportCells(UnitTestCase):
	def test_formula_like_text_is_neutralised(self):
		self.assertEqual([g.csv_cell(v) for v in ("=HYPERLINK(1)", "+1", "-2", "@x", "Asha", 8.5, None)],
			["'=HYPERLINK(1)", "'+1", "'-2", "'@x", "Asha", 8.5, ""])  # fmt: skip


class TestFixRound1(UnitTestCase):
	def test_m1_the_listed_row_is_the_latest_pass_the_cgpa_counts(self):
		improved = [attempt("C1", 6), attempt("C2", 9), attempt("C3", 8), attempt("C4", 9), attempt("C1", 9)]
		record = g.consolidate(improved, {}, 18, 1)
		self.assertEqual([c["grade_point"] for c in record["core_courses"]], [9, 9, 8, 9])
		self.assertEqual(record["cgpa"], 8.75)  # (9 + 9 + 8 + 9) / 4: the same pass as listed

	def test_m6_withdrawn_shortage_and_pending_courses_stay_arrears(self):
		# T21: a withdrawal is not an attempt or appearance but the course is still owed; SA redoes the course;
		# Pending (T19 fix 1) is a registered arrear without marks
		rows = [*STRONG[:1], attempt("C2", 0, "WD"), attempt("C3", 0, "SA"), attempt("C4", 0, "Pending")]
		record = g.consolidate(rows, {}, 18, 1)
		self.assertEqual(record["arrears"], ["C2", "C3", "C4"])
		cleared = g.consolidate([attempt("C2", 0, "WD"), *STRONG], {}, 18, 1)
		self.assertEqual((cleared["arrears"], cleared["first_appearance"]), ([], True))

	def test_m2_core_credits_earned(self):
		record = g.consolidate(
			[*STRONG[:3], attempt("C4", 0, "Fail"), attempt("H1", 10, credits=9)], HONOURS, 18, 1
		)
		self.assertEqual(record["core_credits"], 9)
		self.assertTrue(g.credits_complete(record, 9))
		self.assertFalse(g.credits_complete(record, 12))
		self.assertTrue(g.credits_complete(record, 0))  # no credit total on record: not checked
