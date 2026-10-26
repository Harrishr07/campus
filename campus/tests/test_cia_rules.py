"""M06-08 unit tests: CIA conversion formulas per template, hand-computed (AC1, AC2)."""

from frappe.tests import UnitTestCase

from campus.examinations.cia_rules import component_totals, converted_assessment, converted_cia

# R2022 theory: two assessments of 100, each 40 assignment + 60 test, converted to 40 (weights 8 / 12 / 8 / 12)
R2022_THEORY = [("Assignment 1", 40, 8), ("Test 1", 60, 12), ("Assignment 2", 40, 8), ("Test 2", 60, 12)]
# R2022 lab: 75 observation/record + 25 test, converted to 60
R2022_LAB = [("Observation and Record", 75, 45), ("Test", 25, 15)]
# R2026 theory: the same two assessments converted to 35, plus up to 5 attendance marks
R2026_THEORY = [(c, m, m * 35 / 200) for c, m, _w in R2022_THEORY]


class TestCIAConversion(UnitTestCase):
	def test_r2022_theory_two_assessments_of_100_to_40(self):
		marks = {"Assignment 1": 32, "Test 1": 45, "Assignment 2": 36, "Test 2": 50}
		self.assertEqual(converted_cia(R2022_THEORY, marks), 33)  # 163 / 200 x 40 = 32.6 -> 33

	def test_half_marks_round_half_up(self):
		marks = {"Assignment 1": 30, "Test 1": 42.5, "Assignment 2": 40, "Test 2": 50}
		self.assertEqual(converted_cia(R2022_THEORY, marks), 33)  # 162.5 / 200 x 40 = 32.5 -> 33
		marks["Test 1"] = 42
		self.assertEqual(converted_cia(R2022_THEORY, marks), 32)  # 162 / 200 x 40 = 32.4 -> 32

	def test_a_missing_component_scores_zero(self):
		marks = {"Assignment 1": 30, "Test 1": 40, "Assignment 2": 34}  # absent from Test 2
		self.assertEqual(converted_cia(R2022_THEORY, marks), 21)  # 104 / 200 x 40 = 20.8 -> 21

	def test_r2022_lab_75_plus_25_to_60(self):
		self.assertEqual(
			converted_cia(R2022_LAB, {"Observation and Record": 68, "Test": 19}), 52
		)  # 87 x 0.6 = 52.2
		self.assertEqual(converted_cia(R2022_LAB, {"Observation and Record": 75, "Test": 25}), 60)

	def test_r2026_theory_adds_attendance_marks_after_rounding(self):
		marks = {"Assignment 1": 32, "Test 1": 45, "Assignment 2": 36, "Test 2": 50}
		self.assertEqual(converted_assessment(R2026_THEORY, marks), 29)  # 163 / 200 x 35 = 28.525 -> 29
		self.assertEqual(converted_cia(R2026_THEORY, marks, attendance_marks=3), 32)
		self.assertEqual(converted_cia(R2026_THEORY, marks, attendance_marks=0), 29)

	def test_without_rounding_two_decimals_are_kept(self):
		marks = {"Assignment 1": 32, "Test 1": 45, "Assignment 2": 36, "Test 2": 50}
		self.assertEqual(converted_cia(R2026_THEORY, marks, round_to_integer=False), 28.53)

	def test_component_totals_sum_questions_and_zero_absent_rows(self):
		rows = [
			("S1", "Test 1", 15, 0),
			("S1", "Test 1", 30, 0),
			("S1", "Test 2", 18, 1),
			("S2", "Test 1", None, 0),
		]
		self.assertEqual(
			component_totals(rows), {("S1", "Test 1"): 45, ("S1", "Test 2"): 0, ("S2", "Test 1"): 0}
		)
