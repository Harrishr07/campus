"""P2-T09 (M07-04 / M07-05) unit tests: API scoring with per-year caps and the KRA scores, all hand-computed.

Rule rows used (activity: points per item, annual cap): FDP Attended 4 (cap 8), Conference 3 (cap 6), Award 5 (no cap),
Teaching Workload 1 per weekly hour (cap 20). KRA targets: Teaching 20 points, Professional Development 20 points.
"""

from datetime import date

import frappe
from frappe.tests import UnitTestCase

from campus.faculty import api_scoring, self_appraisal

TEACHING, PD = "Teaching", "Professional Development"
ROWS = [
	frappe._dict(activity="FDP Attended", points=4, annual_cap=8, kra=PD),
	frappe._dict(activity="Conference", points=3, annual_cap=6, kra=PD),
	frappe._dict(activity="Award", points=5, annual_cap=0, kra=PD),
	frappe._dict(activity="Teaching Workload", points=1, annual_cap=20, kra=TEACHING),
]
KRAS = [
	frappe._dict(kra=TEACHING, weightage=60, target_points=20),
	frappe._dict(kra=PD, weightage=40, target_points=20),
]


def year_of(on_date):
	"""Academic years run June to May."""
	return on_date.year if on_date.month >= 6 else on_date.year - 1


def points(results, activity):
	return next(r.points for r in results if r.activity == activity)


class TestApiScoring(UnitTestCase):
	def test_points_are_quantity_times_rule_points(self):
		results = api_scoring.score_activities([("Conference", date(2026, 7, 1), 1)], ROWS, year_of)
		self.assertEqual(points(results, "Conference"), 3)

	def test_cap_applies_per_year(self):
		items = [("FDP Attended", date(2026, 7, d), 1) for d in (1, 2, 3)]  # 12 raw in 2026-27 -> capped at 8
		items += [("FDP Attended", date(2027, 7, 1), 1)]  # 4 in 2027-28, under the cap
		results = api_scoring.score_activities(items, ROWS, year_of)
		self.assertEqual(points(results, "FDP Attended"), 12)  # 8 + 4, not min(16, 8)
		row = next(r for r in results if r.activity == "FDP Attended")
		self.assertEqual((row.quantity, row.raw_points), (4, 16))

	def test_no_cap_when_cap_is_zero(self):
		items = [("Award", date(2026, 7, 1), 1)] * 5
		self.assertEqual(points(api_scoring.score_activities(items, ROWS, year_of), "Award"), 25)

	def test_exactly_at_the_cap_and_one_past_it(self):
		two = [("FDP Attended", date(2026, 7, 1), 2)]
		three = [("FDP Attended", date(2026, 7, 1), 3)]
		self.assertEqual(points(api_scoring.score_activities(two, ROWS, year_of), "FDP Attended"), 8)
		self.assertEqual(points(api_scoring.score_activities(three, ROWS, year_of), "FDP Attended"), 8)

	def test_fractional_quantity_for_workload_hours(self):
		items = [("Teaching Workload", date(2026, 7, 1), 12.5), ("Teaching Workload", date(2027, 7, 5), 10)]
		self.assertEqual(
			points(api_scoring.score_activities(items, ROWS, year_of), "Teaching Workload"), 22.5
		)  # 12.5 + 10, each year under 20

	def test_activity_without_a_rule_row_scores_nothing_and_every_row_is_reported(self):
		results = api_scoring.score_activities([("Membership", date(2026, 7, 1), 3)], ROWS, year_of)
		self.assertEqual(sorted(r.activity for r in results), sorted(r.activity for r in ROWS))
		self.assertEqual(sum(r.points for r in results), 0)

	def test_kra_scores_from_capped_points(self):
		items = [("FDP Attended", date(2026, 7, d), 1) for d in (1, 2, 3)]  # capped 8
		items += [
			("Conference", date(2026, 8, 1), 1),
			("Award", date(2026, 9, 1), 1),
			("Teaching Workload", date(2026, 7, 1), 12),
		]
		kras = api_scoring.kra_scores(api_scoring.score_activities(items, ROWS, year_of), KRAS)
		by_kra = {k.kra: k for k in kras}
		self.assertEqual(
			(by_kra[PD].points, by_kra[PD].completion, by_kra[PD].score), (16, 80, 4)
		)  # 8 + 3 + 5 of 20
		self.assertEqual(
			(by_kra[TEACHING].points, by_kra[TEACHING].completion, by_kra[TEACHING].score), (12, 60, 3)
		)
		self.assertEqual([k.weightage for k in kras], [60, 40])

	def test_completion_is_limited_to_one_hundred_percent(self):
		items = [("Award", date(2026, 7, d), 1) for d in range(1, 8)]  # 35 points against a target of 20
		by_kra = {
			k.kra: k for k in api_scoring.kra_scores(api_scoring.score_activities(items, ROWS, year_of), KRAS)
		}
		self.assertEqual((by_kra[PD].points, by_kra[PD].completion, by_kra[PD].score), (35, 100, 5))

	def test_zero_target_gives_zero_completion(self):
		kras = [frappe._dict(kra=PD, weightage=100, target_points=0)]
		self.assertEqual(
			api_scoring.kra_scores(api_scoring.score_activities([], ROWS, year_of), kras)[0].completion, 0
		)

	def test_phase_three_hooks_return_zero_until_publications_and_feedback_exist(self):
		for activity in ("Publication", "Student Feedback"):
			self.assertEqual(
				self_appraisal.phase3_quantity(activity, "EMP-1", date(2026, 6, 1), date(2027, 5, 31)), 0
			)
