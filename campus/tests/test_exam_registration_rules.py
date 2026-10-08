"""M06-01 unit tests: per-course exam eligibility matrix and the late fee slab, hand-computed."""

from frappe.tests import UnitTestCase

from campus.examinations.registration_rules import (
	ARREAR,
	CURRENT,
	DEBARRED,
	DETAINED,
	DROPPED,
	ELIGIBLE,
	SHORTAGE,
	course_eligibility,
	late_fee,
)

# (kind, attendance shortage, detained, debarred) -> eligibility
MATRIX = [
	(CURRENT, False, False, False, ELIGIBLE),
	(DROPPED, False, False, False, ELIGIBLE),
	(ARREAR, False, False, False, ELIGIBLE),
	# R2022 cl. 15.1: shortage bars the courses attended this term, an arrear stays registrable
	(CURRENT, True, False, False, SHORTAGE),
	(DROPPED, True, False, False, SHORTAGE),
	(ARREAR, True, False, False, ELIGIBLE),
	# detention bars the term's courses only
	(CURRENT, False, True, False, DETAINED),
	(DROPPED, False, True, False, DETAINED),
	(ARREAR, False, True, False, ELIGIBLE),
	# shortage is reported before detention
	(CURRENT, True, True, False, SHORTAGE),
	(ARREAR, True, True, False, ELIGIBLE),
	# malpractice debarment bars every course, and wins over everything else
	(CURRENT, False, False, True, DEBARRED),
	(DROPPED, False, False, True, DEBARRED),
	(ARREAR, False, False, True, DEBARRED),
	(CURRENT, True, True, True, DEBARRED),
	(ARREAR, True, True, True, DEBARRED),
]

# days late (from_day, to_day inclusive) -> late fee
SLABS = [(1, 7, 100), (8, 15, 250)]


class TestCourseEligibility(UnitTestCase):
	def test_eligibility_matrix(self):
		for kind, shortage, detained, debarred, expected in MATRIX:
			with self.subTest(kind=kind, shortage=shortage, detained=detained, debarred=debarred):
				self.assertEqual(course_eligibility(kind, shortage, detained, debarred), expected)

	def test_labels_are_the_documented_ones(self):
		self.assertEqual(
			(ELIGIBLE, SHORTAGE, DETAINED, DEBARRED),
			("Eligible", "Not eligible (SA)", "Not eligible (Detained)", "Not eligible (Debarred)"),
		)

	def test_an_unknown_kind_is_refused(self):
		with self.assertRaises(ValueError):
			course_eligibility("Additional", False, False, False)


class TestLateFee(UnitTestCase):
	def test_on_time_or_early_pays_no_late_fee(self):
		self.assertEqual(late_fee(0, SLABS), 0)
		self.assertEqual(late_fee(-3, SLABS), 0)
		self.assertEqual(late_fee(0, []), 0)

	def test_each_day_falls_in_its_slab_with_inclusive_bounds(self):
		for days, fee in ((1, 100), (7, 100), (8, 250), (10, 250), (15, 250)):
			with self.subTest(days=days):
				self.assertEqual(late_fee(days, SLABS), fee)

	def test_beyond_the_last_slab_registration_is_closed(self):
		self.assertIsNone(late_fee(16, SLABS))
		self.assertIsNone(late_fee(1, []))

	def test_slab_order_does_not_matter(self):
		self.assertEqual(late_fee(9, list(reversed(SLABS))), 250)

	def test_a_gap_between_slabs_is_closed(self):
		self.assertIsNone(late_fee(5, [(1, 3, 50), (8, 15, 250)]))
