"""M05-02 unit tests: attendance eligibility maths, one fixture of scenarios under both regulations."""

from frappe.tests import UnitTestCase

from campus.student_services.attendance_rules import (
	ATTENDED,
	ELIGIBLE,
	MEDICAL_BAND,
	MEDICAL_LEAVE,
	SHORTAGE,
	attendance_marks,
	bucket,
	eligibility,
	overall_percentage,
	session_counts,
	session_mark,
)

COUNTING = {"od_counts": 1, "medical_counts": 1}
R2022 = {
	"formula": "sum_based",
	"overall_min_pct": 75,
	"medical_band_min_pct": 65,
	"per_course_min_pct": 0,
	**COUNTING,
}
R2026 = {
	"formula": "course_average",
	"overall_min_pct": 80,
	"medical_band_min_pct": 70,
	"per_course_min_pct": 75,
	**COUNTING,
}
R2026_BANDS = [(80, 85, 2), (86, 90, 3), (91, 95, 4), (96, None, 5)]

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
	# 72 present + 10 On Duty (counted as attended) of 100 = 82 each: eligible under both
	("on duty counted", [(100, 82, 0), (100, 82, 0)], 82, ELIGIBLE, 82, ELIGIBLE),
	# 66 present + 6 medical of 100: sum 72 >= 65 band; per course 72 < 75 so no band under R2026
	("medical in the band", [(100, 66, 6), (100, 66, 6)], 66, MEDICAL_BAND, 66, SHORTAGE),
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


class TestLeaveKindsAndMarks(UnitTestCase):
	def test_bucket_by_leave_kind_and_rule(self):
		counting, nothing = {"od_counts": 1, "medical_counts": 1}, {"od_counts": 0, "medical_counts": 0}
		cases = [  # status, leave kind, counting rule, rule that counts neither
			("Present", None, ATTENDED, ATTENDED),
			("Absent", None, None, None),
			("Leave", "On Duty", ATTENDED, None),
			("Leave", "Medical", MEDICAL_LEAVE, None),
			("Leave", "Leave", None, None),
			("Leave", None, None, None),
		]
		for status, kind, with_counting, with_nothing in cases:
			with self.subTest(status=status, kind=kind):
				self.assertEqual(bucket(status, kind, counting), with_counting)
				self.assertEqual(bucket(status, kind, nothing), with_nothing)

	def test_attendance_mark_bands(self):
		for pct, marks in [
			(79.4, 0),
			(79.5, 2),
			(80, 2),
			(85.4, 2),
			(85.5, 3),
			(90, 3),
			(90.5, 4),
			(95.4, 4),
			(95.5, 5),
			(100, 5),
		]:
			with self.subTest(pct=pct):
				self.assertEqual(attendance_marks(R2026_BANDS, pct), marks)

	def test_no_bands_means_no_marks(self):
		self.assertEqual(attendance_marks([], 100), 0)


class TestSessionStates(UnitTestCase):
	"""M05-12 which class sessions are conducted, and how a covering leave marks one."""

	def test_only_held_sessions_count(self):
		cases = [  # state, replaced by a makeup, counts
			("Scheduled", False, True), (None, False, True), ("", False, True), ("Conducted", False, True), ("Makeup", False, True),
			("Cancelled", False, False), ("Rescheduled", False, False), ("Conducted", True, False), ("Scheduled", True, False),
		]  # fmt: skip
		for state, replaced, counts in cases:
			with self.subTest(state=state, replaced=replaced):
				self.assertEqual(session_counts(state, replaced), counts)

	def test_a_covering_leave_marks_anything_but_present(self):
		cases = [  # record status, record leave kind, covering leave kind, result
			("Present", None, "Medical", ("Present", None)),
			("Absent", None, "On Duty", ("Leave", "On Duty")),
			(None, None, "Medical", ("Leave", "Medical")),
			("Leave", None, "Medical", ("Leave", "Medical")),
			("Leave", "On Duty", "Medical", ("Leave", "On Duty")),
			("Absent", None, None, ("Absent", None)),
			(None, None, None, (None, None)),
		]
		for status, kind, covering, result in cases:
			with self.subTest(status=status, kind=kind, covering=covering):
				self.assertEqual(session_mark(status, kind, covering), result)

	def test_a_covering_leave_marked_as_present_makes_the_session_present(self):
		cases = [  # record status, record leave kind, covering leave kind, result
			("Absent", None, "On Duty", ("Present", None)),
			(None, None, None, ("Present", None)),
			("Leave", "Medical", "On Duty", ("Leave", "Medical")),  # its own application stands
			("Present", None, "Medical", ("Present", None)),
		]
		for status, kind, covering, result in cases:
			with self.subTest(status=status, kind=kind, covering=covering):
				self.assertEqual(session_mark(status, kind, covering, covering_present=True), result)
