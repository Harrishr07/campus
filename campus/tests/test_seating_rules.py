"""M06-02 unit tests: the seating plan algorithm (examinations.seating_rules), on hand-built halls and mixes.

Properties: no two row/column neighbours share a course when the mix allows it, blocked seats are never used,
capacity is never exceeded, the output does not depend on the input order.
"""

import random

from frappe.tests import UnitTestCase

from campus.examinations.seating_rules import CapacityError, assign, conflicts, hall_seats


def students(**counts):
	"""[(student, course)]: course "A" with 3 gives A-01, A-02, A-03."""
	return [(f"{course}-{n:02}", course) for course, count in counts.items() for n in range(1, count + 1)]


def occupied(plan):
	return {seat: candidate for seat, candidate in plan.items() if candidate}


class TestHallSeats(UnitTestCase):
	def test_seats_run_row_by_row_and_skip_blocked_ones(self):
		seats = hall_seats("H1", 2, 3, {(1, 2), (2, 3)})
		self.assertEqual([(s.row, s.column) for s in seats], [(1, 1), (1, 3), (2, 1), (2, 2)])
		self.assertEqual({s.hall for s in seats}, {"H1"})


class TestInterleaving(UnitTestCase):
	def test_two_equal_courses_fill_a_hall_as_a_checkerboard(self):
		plan = assign(hall_seats("H1", 4, 4), students(A=8, B=8))
		self.assertEqual((len(occupied(plan)), conflicts(plan)), (16, 0))

	def test_three_uneven_courses_have_no_neighbours_alike(self):
		for mix in ({"A": 6, "B": 5, "C": 5}, {"A": 8, "B": 4, "C": 4}, {"A": 5, "B": 4, "C": 3, "D": 2}):
			plan = assign(hall_seats("H1", 4, 4), students(**mix))
			self.assertEqual((len(occupied(plan)), conflicts(plan)), (sum(mix.values()), 0), mix)

	def test_a_single_course_uses_spare_seats_as_gaps(self):
		plan = assign(hall_seats("H1", 4, 4), students(A=8))
		self.assertEqual((len(occupied(plan)), conflicts(plan)), (8, 0))

	def test_feasible_mixes_on_odd_halls_have_no_conflicts(self):
		"""Every mix whose largest course fits one colour of the grid's checkerboard, with no spare seat."""
		for rows, columns in ((3, 3), (3, 5), (5, 4), (6, 7)):
			size = rows * columns
			for courses in (2, 3, 4):
				largest = size // 2
				rest = size - largest
				mix = {
					"A": largest,
					**{
						chr(66 + i): rest // (courses - 1) + (i < rest % (courses - 1))
						for i in range(courses - 1)
					},
				}
				plan = assign(hall_seats("H1", rows, columns), students(**mix))
				self.assertEqual((len(occupied(plan)), conflicts(plan)), (size, 0), (rows, columns, mix))

	def test_an_unavoidable_clash_still_seats_everyone(self):
		plan = assign(hall_seats("H1", 2, 2), students(A=3, B=1))  # A cannot fit one checkerboard colour
		self.assertEqual(len(occupied(plan)), 4)
		self.assertGreater(conflicts(plan), 0)


class TestCapacityAndBlockedSeats(UnitTestCase):
	def test_more_students_than_seats_is_refused(self):
		with self.assertRaises(CapacityError):
			assign(hall_seats("H1", 2, 2, {(1, 1)}), students(A=2, B=2))

	def test_blocked_seats_stay_empty(self):
		seats = hall_seats("H1", 3, 3, {(2, 2)})
		plan = assign(seats, students(A=4, B=4))
		self.assertEqual(len(occupied(plan)), 8)
		self.assertNotIn((2, 2), {(s.row, s.column) for s in plan})
		self.assertEqual(conflicts(plan), 0)

	def test_neighbours_in_different_halls_do_not_clash_and_each_hall_holds_its_seats(self):
		seats = hall_seats("H1", 2, 2) + hall_seats("H2", 2, 3)
		plan = assign(seats, students(A=5, B=5))
		self.assertEqual((len(occupied(plan)), conflicts(plan)), (10, 0))
		self.assertEqual(sum(1 for s in occupied(plan) if s.hall == "H1"), 4)


class TestDeterminism(UnitTestCase):
	def test_the_input_order_does_not_change_the_plan(self):
		seats, candidates = hall_seats("H1", 4, 5, {(1, 1)}), students(A=7, B=6, C=5)
		expected = assign(seats, candidates)
		shuffled = list(candidates)
		random.Random(7).shuffle(shuffled)
		self.assertEqual(assign(seats, shuffled), expected)


class TestConflicts(UnitTestCase):
	def test_conflicts_count_row_and_column_neighbours_of_one_hall(self):
		a, b = hall_seats("H1", 2, 2), hall_seats("H2", 1, 1)
		plan = {a[0]: ("s1", "A"), a[1]: ("s2", "A"), a[2]: ("s3", "A"), a[3]: ("s4", "B"), b[0]: ("s5", "A")}
		self.assertEqual(conflicts(plan), 2)  # (1,1)-(1,2) and (1,1)-(2,1); H2 is another room
