"""P2-T07 (M07-03) unit tests: the hard-constraint validator on hand-built grids, the soft-constraint report and the
pure-Python solver (clash-free result, unmet constraints reported, demo scale inside the time limit)."""

import time

from frappe.tests import UnitTestCase

from campus.faculty.timetable import rules, solver
from campus.faculty.timetable.rules import Entry, Grid, Room
from campus.faculty.timetable.solver import Problem, Session

DAYS = ["Monday", "Tuesday", "Wednesday"]
PERIODS = {1: False, 2: False, 3: True, 4: False, 5: False}  # period 3 is the break


def make_grid(**extra):
	values = {
		"days": DAYS, "periods": PERIODS, "lab_block": 2, "max_faculty_periods_per_day": 3,
		"rooms": {"C1": Room(40, False), "C2": Room(40, False), "L1": Room(40, True), "SMALL": Room(20, False)},
		"strengths": {"DS-A": 30, "DS-B": 30, "LAB-A": 30}, "unavailable": set(),
	}  # fmt: skip
	return Grid(**{**values, **extra})


def entry(offering="DS-A", section="CSE-3-A", faculty="T1", room="C1", day="Monday", period=1, kind="Lecture"):
	return Entry(offering, section, faculty, room, day, period, kind)


def rules_of(entries, grid=None):
	return sorted(v.rule for v in rules.violations(entries, grid or make_grid()))


class TestHardConstraints(UnitTestCase):
	def test_a_clean_grid_has_no_violations(self):
		entries = [
			entry(period=1), entry(offering="DS-B", section="CSE-3-B", faculty="T2", room="C2", period=1),
			entry(period=2, day="Tuesday"),
			entry("LAB-A", faculty="T3", room="L1", day="Monday", period=4, kind="Practical"),
			entry("LAB-A", faculty="T3", room="L1", day="Monday", period=5, kind="Practical"),
		]  # fmt: skip
		self.assertEqual(rules.violations(entries, make_grid()), [])

	def test_faculty_clash(self):
		entries = [entry(), entry(offering="DS-B", section="CSE-3-B", room="C2")]  # T1 in two sections at once
		self.assertEqual(rules_of(entries), [rules.FACULTY_CLASH])

	def test_room_clash(self):
		entries = [entry(), entry(offering="DS-B", section="CSE-3-B", faculty="T2")]  # both in C1
		self.assertEqual(rules_of(entries), [rules.ROOM_CLASH])

	def test_section_clash(self):
		entries = [entry(), entry(offering="DS-X", faculty="T2", room="C2")]  # section CSE-3-A has two classes at once
		self.assertEqual(rules_of(entries), [rules.SECTION_CLASH])

	def test_same_period_on_another_day_is_not_a_clash(self):
		self.assertEqual(rules_of([entry(), entry(day="Tuesday")]), [])

	def test_break_unknown_period_and_unknown_day_are_invalid_slots(self):
		for bad in (entry(period=3), entry(period=9), entry(day="Sunday")):
			self.assertEqual(rules_of([bad]), [rules.INVALID_SLOT], bad)

	def test_faculty_unavailability(self):
		grid = make_grid(unavailable={("T1", "Monday", 1)})
		self.assertEqual(rules_of([entry()], grid), [rules.UNAVAILABLE])
		self.assertEqual(rules_of([entry(period=2)], grid), [])
		self.assertEqual(rules_of([entry(faculty="T2")], grid), [])

	def test_practical_needs_a_lab_and_lectures_stay_out_of_labs(self):
		self.assertEqual(rules_of([entry(kind="Practical", period=1), entry(kind="Practical", period=2)]), [rules.LAB_ROOM] * 2)
		self.assertEqual(rules_of([entry(room="L1")]), [rules.LAB_ROOM])

	def test_room_capacity(self):
		self.assertEqual(rules_of([entry(room="SMALL")]), [rules.CAPACITY])  # 20 seats for 30 students
		self.assertEqual(rules_of([entry(room="SMALL")], make_grid(strengths={})), [])  # unknown strength: no check

	def test_lab_periods_must_be_consecutive_in_one_room(self):
		def lab(period, room="L1", day="Monday"):
			return entry("LAB-A", faculty="T3", room=room, day=day, period=period, kind="Practical")

		self.assertEqual(rules_of([lab(1), lab(2)]), [])
		self.assertEqual(rules_of([lab(1), lab(4)]), [rules.LAB_BLOCK])  # period 2, 3 (break) between
		self.assertEqual(rules_of([lab(2), lab(4)]), [rules.LAB_BLOCK])  # the break splits the block
		self.assertEqual(rules_of([lab(1), lab(2, day="Tuesday")]), [])  # one period on two days: two blocks
		grid = make_grid(rooms={**make_grid().rooms, "L2": Room(40, True)})
		self.assertEqual(rules_of([lab(1), lab(2, room="L2")], grid), [rules.LAB_BLOCK])  # block moves between labs

	def test_violation_messages_name_the_slot_and_the_parties(self):
		(violation,) = rules.violations([entry(), entry(offering="DS-B", section="CSE-3-B", room="C2")], make_grid())
		self.assertEqual((violation.day, violation.period, violation.subject), ("Monday", 1, "T1"))
		self.assertIn("T1", violation.message)
		self.assertIn("Monday", violation.message)


class TestSoftConstraints(UnitTestCase):
	def test_a_course_twice_a_day_and_faculty_over_the_daily_maximum_are_reported(self):
		entries = [entry(period=1), entry(period=2), entry(offering="DS-B", section="B", faculty="T1", room="C2", period=4),
			entry(offering="DS-C", section="C", faculty="T1", room="C2", period=5)]  # fmt: skip
		issues = rules.soft_issues(entries, make_grid())
		self.assertEqual(sorted(i.rule for i in issues), [rules.SAME_DAY_REPEAT, rules.DAILY_MAXIMUM])
		self.assertEqual(len(rules.soft_issues([entry(period=1), entry(period=2, day="Tuesday")], make_grid())), 0)

	def test_a_practical_block_is_not_a_repeat(self):
		lab = [entry("LAB-A", faculty="T3", room="L1", period=p, kind="Practical") for p in (1, 2)]
		self.assertEqual(rules.soft_issues(lab, make_grid()), [])


def session(sid, offering="DS-A", section="CSE-3-A", faculty="T1", kind="Lecture", length=1, strength=30):
	return Session(sid, offering, section, faculty, kind, length, strength)


def small_problem(sessions, **grid_extra):
	return Problem(grid=make_grid(**grid_extra), sessions=sessions)


class TestSolver(UnitTestCase):
	def test_places_every_session_without_hard_violations(self):
		sessions = [session(1), session(2), session(3, offering="DS-B", section="CSE-3-B", faculty="T2"),
			session(4, offering="LAB-A", faculty="T3", kind="Practical", length=2)]  # fmt: skip
		result = solver.solve(small_problem(sessions))
		self.assertEqual(result.unmet, [])
		self.assertEqual(len(result.entries), 5)
		self.assertEqual(rules.violations(result.entries, make_grid()), [])

	def test_a_lecture_course_is_spread_over_different_days(self):
		result = solver.solve(small_problem([session(i) for i in (1, 2, 3)]))
		self.assertEqual(len({e.day for e in result.entries}), 3)

	def test_an_unplaceable_session_is_reported_with_the_reason(self):
		grid = {"unavailable": {("T1", day, p) for day in DAYS for p in (1, 2, 4, 5)}}
		result = solver.solve(small_problem([session(1), session(2, faculty="T2", offering="DS-B", section="B")], **grid))
		self.assertEqual(len(result.entries), 1)
		self.assertEqual(len(result.unmet), 1)
		self.assertIn("T1", result.unmet[0])
		self.assertIn("unavailable", result.unmet[0])

	def test_no_lab_big_enough_is_reported_up_front(self):
		result = solver.solve(small_problem([session(1, offering="LAB-A", faculty="T3", kind="Practical", length=2, strength=60)]))
		self.assertEqual(result.entries, [])
		self.assertIn("no Lab room", result.unmet[0])

	def test_a_block_longer_than_any_run_of_periods_is_reported(self):
		result = solver.solve(small_problem([session(1, kind="Practical", length=3)]))  # runs are 1-2 and 4-5 only
		self.assertEqual(len(result.unmet), 1)

	def test_a_faculty_with_more_hours_than_slots_places_what_fits(self):
		sessions = [session(i, offering=f"O{i}", section=f"S{i}", faculty="T1") for i in range(1, 15)]  # 14 hours, 12 slots
		result = solver.solve(small_problem(sessions, strengths={}))
		self.assertEqual((len(result.entries), len(result.unmet)), (12, 2))
		self.assertEqual(rules.violations(result.entries, make_grid(strengths={})), [])

	def test_result_is_repeatable(self):
		sessions = [session(i, offering=f"O{i % 3}", faculty=f"T{i % 2}") for i in range(6)]
		first, second = solver.solve(small_problem(sessions)), solver.solve(small_problem(sessions))
		self.assertEqual(first.entries, second.entries)


def demo_scale_problem():
	"""2 programs x 4 years x 2 sections = 16 sections; each has 5 theory courses (3 lectures + 1 tutorial a week)
	and 2 labs (4 practical hours = two 2-period blocks): 28 of the 35 weekly periods. 24 teachers, 12 classrooms, 6 labs."""
	periods = {1: False, 2: False, 3: False, 4: True, 5: False, 6: False, 7: False, 8: False}  # 7 teaching periods
	rooms = {f"C{i}": Room(60, False) for i in range(12)} | {f"L{i}": Room(30, True) for i in range(6)}
	sessions, strengths, sid = [], {}, 0
	for number in range(16):
		section = f"S{number}"
		for course in range(7):
			offering = f"{section}-C{course}"
			strengths[offering] = 30
			teacher = f"T{(number * 7 + course) % 24}"
			lab = course >= 5
			shapes = [("Practical", 2)] * 2 if lab else [("Lecture", 1)] * 3 + [("Tutorial", 1)]
			for kind, length in shapes:
				sessions.append(Session(sid, offering, section, teacher, kind, length, 30))
				sid += 1
	grid = Grid(days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], periods=periods, rooms=rooms, strengths=strengths,
		unavailable=set(), lab_block=2, max_faculty_periods_per_day=6)  # fmt: skip
	return Problem(grid=grid, sessions=sessions, time_limit=240)


class TestDemoScale(UnitTestCase):
	def test_demo_scale_is_clash_free_well_inside_five_minutes(self):
		problem = demo_scale_problem()
		started = time.monotonic()
		result = solver.solve(problem)
		self.assertLess(time.monotonic() - started, 300)
		self.assertEqual(result.unmet, [])
		self.assertEqual(len(result.entries), 16 * 28)
		self.assertEqual(rules.violations(result.entries, problem.grid), [])
