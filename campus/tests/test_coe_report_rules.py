"""M17-06 unit tests of the COE report rules (campus.examinations.coe_report_rules): appeared / passed tallies,
pass percentage, competition ranks, days from the exam end to the result and their average."""

from frappe.tests import UnitTestCase

from campus.examinations import coe_report_rules as rules


def row(result, course, outcome, group="G"):
	return {"result": result, "course": course, "outcome": outcome, "group": group}


class TestTally(UnitTestCase):
	def by_result(self, rows):
		return rules.tally(rows, lambda r: r["group"], lambda r: r["result"])

	def test_a_result_appears_with_one_sitting_and_passes_only_when_every_course_is_a_pass(self):
		rows = [
			row("R1", "C1", "Pass"), row("R1", "C2", "Pass"),  # appeared, passed
			row("R2", "C1", "Pass"), row("R2", "C2", "Fail"),  # appeared, failed
			row("R3", "C1", "AB"), row("R3", "C2", "Pass"),  # appeared (one sitting), not passed (absent)
			row("R4", "C1", "SA"), row("R4", "C2", "SA"),  # never sat: not appeared
		]  # fmt: skip
		self.assertEqual(self.by_result(rows), {"G": {"appeared": 3, "passed": 1}})

	def test_withdrawn_and_pending_rows_are_not_sittings(self):
		self.assertEqual(self.by_result([row("R1", "C1", "WD"), row("R1", "C2", "Pending")]), {})

	def test_course_units_count_each_sitting_by_its_own_group(self):
		rows = [
			row("R1", "C1", "Pass", "C1"),
			row("R1", "C2", "Fail", "C2"),
			row("R2", "C1", "Fail", "C1"),
			row("R2", "C2", "AB", "C2"),
		]
		tally = rules.tally(rows, lambda r: r["group"], lambda r: (r["result"], r["course"]))
		self.assertEqual(tally, {"C1": {"appeared": 2, "passed": 1}, "C2": {"appeared": 1, "passed": 0}})

	def test_percent_rounds_to_two_places_and_is_zero_without_a_denominator(self):
		self.assertEqual(rules.percent(1, 3), 33.33)
		self.assertEqual(rules.percent(2, 3), 66.67)
		self.assertEqual(rules.percent(0, 0), 0)


class TestRanksAndDays(UnitTestCase):
	def test_competition_ranks_share_a_rank_on_a_tie_and_skip_the_next(self):
		self.assertEqual(rules.competition_ranks([9.5, 9.0, 9.0, 8.0]), [1, 2, 2, 4])
		self.assertEqual(rules.competition_ranks([]), [])

	def test_days_from_the_exam_end_to_the_declaration_day(self):
		self.assertEqual(rules.days_to_result("2023-02-20", "2023-03-12 10:00:00"), 20)
		self.assertIsNone(rules.days_to_result(None, "2023-03-12 10:00:00"))
		self.assertIsNone(rules.days_to_result("2023-02-20", None))

	def test_average_rounds_and_is_zero_for_nothing(self):
		self.assertEqual(rules.average([20, 25, 31]), 25.33)
		self.assertEqual(rules.average([]), 0)
