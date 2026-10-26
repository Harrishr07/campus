"""M06-03 unit tests: the question paper release window and the blueprint check (CO coverage, Bloom distribution)."""

from datetime import datetime

from frappe.tests import UnitTestCase

from campus.examinations.question_paper_rules import blueprint_issues, in_window, release_window

RELEASE = datetime(2026, 11, 2, 10, 0)


def question(co, bloom, marks, paper_set="A"):
	return {"paper_set": paper_set, "course_outcome": co, "bloom_level": bloom, "marks": marks}


def row(criterion, value, low, high=100):
	return {"criterion": criterion, "value": value, "min_percent": low, "max_percent": high}


BLUEPRINT = [
	row("Course Outcome", "CO1", 40, 60),
	row("Course Outcome", "CO2", 40, 60),
	row("Bloom Level", "Remember", 0, 50),
	row("Bloom Level", "Apply", 50),
]
GOOD = [
	question("CO1", "Remember", 25),
	question("CO1", "Apply", 25),
	question("CO2", "Remember", 25),
	question("CO2", "Apply", 25),
]


class TestReleaseWindow(UnitTestCase):
	def test_window_opens_lead_minutes_before_release_and_closes_when_the_slot_ends(self):
		self.assertEqual(
			release_window(RELEASE, 30, 180), (datetime(2026, 11, 2, 9, 30), datetime(2026, 11, 2, 13, 0))
		)

	def test_in_window_includes_both_ends_only(self):
		opens, closes = release_window(RELEASE, 30, 180)
		self.assertFalse(in_window(datetime(2026, 11, 2, 9, 29, 59), opens, closes))
		self.assertTrue(in_window(opens, opens, closes))
		self.assertTrue(in_window(closes, opens, closes))
		self.assertFalse(in_window(datetime(2026, 11, 2, 13, 0, 1), opens, closes))


class TestBlueprint(UnitTestCase):
	def test_a_paper_that_matches_the_pattern_has_no_issues(self):
		self.assertEqual(blueprint_issues(GOOD + [dict(q, paper_set="B") for q in GOOD], BLUEPRINT, 100), [])

	def test_set_total_must_equal_the_paper_total(self):
		self.assertEqual(
			blueprint_issues(GOOD[:3], BLUEPRINT, 100),
			["Set A: the questions carry 75 marks, the paper 100."],
		)

	def test_the_pattern_needs_a_co_row_and_a_bloom_row(self):
		self.assertEqual(blueprint_issues(GOOD, [], 100), ["The pattern needs at least one Course Outcome row.",
			"The pattern needs at least one Bloom Level row."])  # fmt: skip
		self.assertEqual(
			blueprint_issues(GOOD, BLUEPRINT[:2], 100), ["The pattern needs at least one Bloom Level row."]
		)

	def test_a_pattern_row_with_min_above_max_is_reported(self):
		issues = blueprint_issues(GOOD, [*BLUEPRINT, row("Course Outcome", "CO3", 70, 20)], 100)
		self.assertIn("CO3: the minimum share (70%) is above the maximum (20%).", issues)

	def test_a_set_with_a_paper_file_needs_questions(self):
		self.assertEqual(
			blueprint_issues(GOOD, BLUEPRINT, 100, sets_with_files=("A", "B")),
			["Set B has a paper file but no questions."],
		)

	def test_an_uncovered_course_outcome_is_reported(self):
		questions = [question("CO1", "Apply", 50), question("CO1", "Remember", 50)]
		issues = blueprint_issues(
			questions,
			BLUEPRINT[:2] + [row("Bloom Level", "Apply", 0), row("Bloom Level", "Remember", 0)],
			100,
		)
		self.assertEqual(issues, ["Set A: CO1 carries 100% of the marks, the pattern allows 40% to 60%.",
			"Set A: CO2 is not covered (the pattern needs at least 40%)."])  # fmt: skip

	def test_a_question_outside_the_pattern_course_outcomes_is_reported(self):
		questions = GOOD[:3] + [question("CO3", "Apply", 25)]
		issues = blueprint_issues(questions, BLUEPRINT[:1] + BLUEPRINT[2:], 100)
		self.assertIn("Set A: CO3 is not in the pattern.", issues)

	def test_bloom_distribution_outside_its_range_is_reported(self):
		questions = [
			question("CO1", "Remember", 50),
			question("CO2", "Remember", 25),
			question("CO2", "Apply", 25),
		]
		issues = blueprint_issues(questions, BLUEPRINT, 100)
		self.assertEqual(issues, [
			"Set A: Remember carries 75% of the marks, the pattern allows 0% to 50%.",
			"Set A: Apply carries 25% of the marks, the pattern allows 50% to 100%.",
		])  # fmt: skip

	def test_each_set_is_checked_on_its_own(self):
		questions = GOOD + [question("CO1", "Apply", 100, "B")]
		issues = blueprint_issues(questions, BLUEPRINT, 100)
		self.assertTrue(issues and all(i.startswith("Set B: ") for i in issues), issues)

	def test_a_paper_without_questions_fails(self):
		self.assertEqual(blueprint_issues([], BLUEPRINT, 100), ["The paper has no questions."])
		self.assertEqual(blueprint_issues([], [], 100)[-1], "The paper has no questions.")
