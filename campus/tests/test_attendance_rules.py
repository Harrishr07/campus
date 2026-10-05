"""M05-02 unit tests: attendance eligibility maths, one fixture of scenarios under both regulations."""

from frappe.tests import UnitTestCase

from campus.student_services.attendance_rules import ELIGIBLE, MEDICAL_BAND, SHORTAGE, eligibility, overall_percentage

R2022 = {"formula": "sum_based", "overall_min_pct": 75, "medical_band_min_pct": 65, "per_course_min_pct": 0}
R2026 = {"formula": "course_average", "overall_min_pct": 80, "medical_band_min_pct": 70, "per_course_min_pct": 75}

# name, courses [(conducted, attended, approved leave)], R2022 overall %, R2022 status, R2026 overall %, R2026 status.
# Overall % is of attended periods without leave; every figure is hand computed.
SCENARIOS = [
	# 72/80 = 90 under sum; mean(90, 90) = 90; every course >= 75
	("comfortable", [(40, 36, 0), (40, 36, 0)], 90, ELIGIBLE, 90, ELIGIBLE),
	# sum 62/80 = 77.5 passes 75; mean(70, 85) = 77.5 misses 80
	("average misses 80", [(40, 28, 0), (40, 34, 0)], 77.5, ELIGIBLE, 77.5, SHORTAGE),
	# sum 70/80 = 87.5; mean(100, 50) = 75 misses 80 and the 50% course misses 75
	("one weak small course", [(60, 60, 0), (20, 10, 0)], 87.5, ELIGIBLE, 75, SHORTAGE),
	# raw 69 and 69; leave lifts sum to 74/100 >= 65 (band); per course 74, 74 < 75 so no band under R2026
	("leave lifts R2022 only", [(50, 34, 3), (50, 35, 2)], 69, MEDICAL_BAND, 69, SHORTAGE),
	# raw 73; with leave 77 and 77: band under both (>= 65 / >= 70, and each course >= 75)
	("band under both", [(100, 72, 5), (100, 74, 3)], 73, MEDICAL_BAND, 73, MEDICAL_BAND),
	# 70% and no leave: below 75 and no medical cover
	("short without leave", [(50, 35, 0), (50, 35, 0)], 70, SHORTAGE, 70, SHORTAGE),
	# raw 52.5; with leave 57.5 below both band minimums
	("below the band", [(100, 55, 5), (100, 50, 5)], 52.5, SHORTAGE, 52.5, SHORTAGE),
	# exactly 75 each: sum meets 75; mean 75 misses 80
	("exact 75", [(100, 75, 0), (100, 75, 0)], 75, ELIGIBLE, 75, SHORTAGE),
	# mean(85, 75) = 80 exactly and the 75% course meets its minimum; sum 160/200 = 80
	("exact 80 and 75", [(100, 85, 0), (100, 75, 0)], 80, ELIGIBLE, 80, ELIGIBLE),
	# a course with nothing conducted does not count: only the 8/10 course
	("empty course ignored", [(0, 0, 0), (10, 8, 0)], 80, ELIGIBLE, 80, ELIGIBLE),
]


class TestAttendanceRules(UnitTestCase):
	def test_scenarios_under_both_regulations(self):
		for name, courses, pct_2022, status_2022, pct_2026, status_2026 in SCENARIOS:
			raw = [(conducted, attended) for conducted, attended, _leave in courses]
			with self.subTest(name):
				self.assertEqual(overall_percentage(R2022["formula"], raw), pct_2022)
				self.assertEqual(eligibility(R2022, courses), status_2022)
				self.assertEqual(overall_percentage(R2026["formula"], raw), pct_2026)
				self.assertEqual(eligibility(R2026, courses), status_2026)

	def test_same_attendance_gives_different_outcomes_by_regulation(self):
		courses = [(40, 28, 0), (40, 34, 0)]
		self.assertEqual((eligibility(R2022, courses), eligibility(R2026, courses)), (ELIGIBLE, SHORTAGE))

	def test_nothing_conducted_is_not_a_shortage(self):
		self.assertIsNone(overall_percentage("sum_based", [(0, 0)]))
		self.assertEqual(eligibility(R2026, [(0, 0, 0)]), ELIGIBLE)

	def test_per_course_minimum_zero_means_none(self):
		self.assertEqual(eligibility(R2022, [(100, 100, 0), (100, 50, 0)]), ELIGIBLE)
