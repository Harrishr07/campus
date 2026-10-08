"""M06-02 unit tests: the invigilation roster (examinations.invigilation_rules), on hand-built sittings.

Properties: duties are balanced within one per faculty per session type (FN / AN), nobody invigilates a hall
holding their own course, nobody on leave that day is used, one hall per faculty per sitting.
"""

from collections import Counter

from frappe.tests import UnitTestCase

from campus.examinations.invigilation_rules import Hall, assign

FACULTY = ["E1", "E2", "E3", "E4"]


def halls(days, slots=("FN", "AN"), rooms=("R1", "R2"), courses=None):
	return [
		Hall(f"2026-11-{day:02}", slot, room, frozenset((courses or {}).get(room, {"X"})))
		for day in range(1, days + 1)
		for slot in slots
		for room in rooms
	]


def spread(duties, slot):
	counts = Counter(employee for hall, employee in duties if hall.slot == slot)
	loads = [counts[e] for e in FACULTY]
	return max(loads) - min(loads)


class TestBalance(UnitTestCase):
	def test_duties_are_within_one_per_faculty_per_session_type(self):
		duties, unfilled = assign(halls(5, rooms=("R1", "R2", "R3")), FACULTY)
		self.assertEqual((len(duties), unfilled), (30, []))
		self.assertLessEqual(spread(duties, "FN"), 1)
		self.assertLessEqual(spread(duties, "AN"), 1)

	def test_two_invigilators_per_hall(self):
		duties, unfilled = assign(halls(2, rooms=("R1",)), FACULTY, per_hall=2)
		self.assertEqual((len(duties), unfilled), (8, []))
		self.assertEqual(spread(duties, "FN"), 0)

	def test_balance_holds_with_own_course_and_leave_exclusions(self):
		sittings = halls(6, courses={"R1": {"C1"}, "R2": {"C2"}})
		duties, unfilled = assign(sittings, FACULTY, own_courses={"E1": {"C1"}}, on_leave={("E2", "2026-11-03")})
		self.assertEqual(unfilled, [])
		self.assertLessEqual(spread(duties, "FN"), 1)
		self.assertLessEqual(spread(duties, "AN"), 1)


class TestExclusions(UnitTestCase):
	def test_nobody_invigilates_a_hall_with_their_own_course(self):
		sittings = halls(3, courses={"R1": {"C1", "C9"}, "R2": {"C2"}})
		duties, _unfilled = assign(sittings, FACULTY, own_courses={"E1": {"C1"}, "E2": {"C2"}})
		self.assertFalse([h for h, e in duties if e == "E1" and h.room == "R1"])
		self.assertFalse([h for h, e in duties if e == "E2" and h.room == "R2"])

	def test_nobody_on_leave_that_day_is_used(self):
		duties, _unfilled = assign(halls(2), FACULTY, on_leave={("E3", "2026-11-01")})
		self.assertFalse([h for h, e in duties if e == "E3" and h.date == "2026-11-01"])
		self.assertTrue([h for h, e in duties if e == "E3" and h.date == "2026-11-02"])

	def test_one_hall_per_faculty_per_sitting(self):
		duties, _unfilled = assign(halls(2, rooms=("R1", "R2", "R3", "R4")), FACULTY)
		sittings = Counter((h.date, h.slot, e) for h, e in duties)
		self.assertEqual(max(sittings.values()), 1)

	def test_a_hall_nobody_may_take_is_reported_unfilled(self):
		sittings = halls(1, slots=("FN",), rooms=("R1", "R2", "R3"))
		duties, unfilled = assign(sittings, ["E1", "E2"])
		self.assertEqual((len(duties), [h.room for h in unfilled]), (2, ["R3"]))


class TestDeterminism(UnitTestCase):
	def test_the_input_order_does_not_change_the_roster(self):
		sittings = halls(3, rooms=("R1", "R2", "R3"))
		expected = assign(sittings, FACULTY)
		self.assertEqual(assign(list(reversed(sittings)), list(reversed(FACULTY))), expected)
