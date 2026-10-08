"""M07-03 Pure-Python timetable search.

Sessions are placed most-constrained first. Each session tries its cheapest few (day, start period, room) options in
turn; when none fits, the search backs up to the previous session (chronological backtracking, bounded by a node
budget and the time limit). If the budget runs out, the deepest partial timetable is kept and the remaining sessions
are placed greedily; whatever still has no slot is reported as unmet with the reasons.

Hard constraints are the rules of `rules`. Cost (soft): a course twice on a day, a teacher past the daily maximum,
unbalanced section days and late periods.
"""

import time
from collections import Counter

from frappe import _

from campus.faculty.timetable import rules
from campus.faculty.timetable.rules import PRACTICAL, Entry
from campus.faculty.timetable.solver import Result

TRIES_PER_SESSION = 6
ROOM_TRIES = 3  # free rooms offered per slot, smallest first
ROOM_RANK_COST = 0.01  # a bigger room is only used when the search backs up
NODE_BUDGET = 4000
ATTEMPTS = 100
REPEAT_COST, OVERLOAD_COST, BALANCE_COST, LATE_COST = 10, 20, 1, 0.1


def solve(problem):
	"""The best of several attempts: sessions left without a slot are moved to the front of the next attempt's order."""
	search = Search(problem)
	unmet = search.pre_check()
	sessions = [s for s in problem.sessions if s.id not in search.hopeless]
	bumped = Counter()
	best = None
	for _attempt in range(ATTEMPTS):
		failed = search.attempt(search.order(sessions, bumped))
		if best is None or len(failed) < len(best[0]):
			best = (failed, dict(search.placements))
		if not failed or time.monotonic() > search.deadline:
			break
		bumped.update(s.id for s in failed)
	failed, placements = best
	search.restore(placements)  # so the unmet reasons describe the timetable that is returned
	entries = sorted(search.entries(), key=lambda e: (e.section, e.day, e.period, e.offering))
	choices = {sid: choice for sid, (_session, choice) in search.placements.items()}
	return Result(entries, unmet + [search.explain(s) for s in failed], len(rules.soft_issues(entries, problem.grid)), placements=choices, unplaced=len(search.hopeless) + len(failed))


class Search:
	def __init__(self, problem):
		self.problem = problem
		self.grid = problem.grid
		self.teaching = rules.teaching_periods(self.grid)
		self.deadline = time.monotonic() + problem.time_limit
		self.hopeless = set()
		self.placements = {}
		self.cache = {}
		self.reset()

	def reset(self):
		self.faculty_busy, self.room_busy, self.section_busy = set(), set(), set()
		self.faculty_day, self.section_day, self.course_day = Counter(), Counter(), Counter()
		self.placements = {}

	# --- what can never fit -------------------------------------------------------------------

	def starts(self, length):
		"""Start periods from which `length` teaching periods follow one another with no break between."""
		key = ("starts", length)
		if key not in self.cache:
			periods = set(self.teaching)
			self.cache[key] = [p for p in self.teaching if all(p + i in periods for i in range(length))]
		return self.cache[key]

	def eligible_rooms(self, session):
		"""Rooms of the right kind that seat the section, smallest first so big rooms stay free."""
		lab = session.kind == PRACTICAL
		key = ("rooms", lab, session.strength)
		if key not in self.cache:
			rooms = [(r.capacity, name) for name, r in self.grid.rooms.items() if r.is_lab == lab and not (r.capacity and session.strength > r.capacity)]
			self.cache[key] = [name for _capacity, name in sorted(rooms)]
		return self.cache[key]

	def pre_check(self):
		"""Sessions that cannot be placed whatever else happens, reported before the search starts."""
		unmet = []
		for session in self.problem.sessions:
			reason = None
			if not self.starts(session.length):
				reason = _("{0} {1} ({2}): the template has no run of {3} consecutive teaching periods.").format(
					session.offering, _(session.kind), session.faculty, session.length)  # fmt: skip
			elif not self.eligible_rooms(session):
				reason = _("{0} {1} ({2}): no {3} room seats {4} students.").format(
					session.offering, _(session.kind), session.faculty, _("Lab") if session.kind == PRACTICAL else _("Classroom"), session.strength)  # fmt: skip
			if reason:
				unmet.append(reason)
				self.hopeless.add(session.id)
		return unmet

	def order(self, sessions, bumped=None):
		bumped = bumped or {}
		"""Sessions that failed before first, then most constrained first: longer blocks, busier teachers, fewer start slots."""
		load = Counter()
		for s in sessions:
			load[s.faculty] += s.length
		starts = {n: len(self.starts(n)) for n in {s.length for s in sessions}}
		return sorted(sessions, key=lambda s: (-bumped.get(s.id, 0), -s.length, s.kind != PRACTICAL, -load[s.faculty], starts[s.length], s.id))

	# --- state ---------------------------------------------------------------------------------

	def slots(self, session, day, start):
		return [(day, start + i) for i in range(session.length)]

	def place(self, session, choice):
		day, start, room = choice
		self.placements[session.id] = (session, choice)
		for slot in self.slots(session, day, start):
			self.faculty_busy.add((session.faculty, *slot))
			self.room_busy.add((room, *slot))
			self.section_busy.add((session.section, *slot))
		self.faculty_day[(session.faculty, day)] += session.length
		self.section_day[(session.section, day)] += session.length
		self.course_day[self.course_key(session, day)] += 1

	def unplace(self, session, choice):
		day, start, room = choice
		del self.placements[session.id]
		for slot in self.slots(session, day, start):
			self.faculty_busy.discard((session.faculty, *slot))
			self.room_busy.discard((room, *slot))
			self.section_busy.discard((session.section, *slot))
		self.faculty_day[(session.faculty, day)] -= session.length
		self.section_day[(session.section, day)] -= session.length
		self.course_day[self.course_key(session, day)] -= 1

	@staticmethod
	def course_key(session, day):
		"""Lectures and tutorials repeat per kind; a practical block per teacher (it cannot be split on a day)."""
		return (session.offering, session.kind, session.faculty if session.kind == PRACTICAL else "", day)

	def attempt(self, order):
		"""Search, then place the rest greedily; returns the sessions that found no slot."""
		placed = self.depth_first(order)
		self.reset()
		for session, choice in zip(order, placed):
			self.place(session, choice)
		failed = []
		for session in order[len(placed) :]:
			choice = self.best(session)
			if choice:
				self.place(session, choice)
			else:
				failed.append(session)
		return failed

	def restore(self, placements):
		self.reset()
		for session, choice in placements.values():
			self.place(session, choice)

	def entries(self):
		return [
			Entry(s.offering, s.section, s.faculty, room, day, start + i, s.kind)
			for s, (day, start, room) in self.placements.values()
			for i in range(s.length)
		]  # fmt: skip

	# --- options -------------------------------------------------------------------------------

	def blocker(self, session, day, start):
		"""Why (day, start) is closed to the session for reasons other than a room, or None."""
		slots = self.slots(session, day, start)
		if any((session.faculty, day, p) in self.grid.unavailable for _d, p in slots):
			return "unavailable"
		if any((session.faculty, *slot) in self.faculty_busy for slot in slots):
			return "faculty"
		if any((session.section, *slot) in self.section_busy for slot in slots):
			return "section"
		if session.kind == PRACTICAL and self.course_day[self.course_key(session, day)]:
			return "section"  # the day already has this course's practical block
		return None

	def free_rooms(self, session, day, start, rooms):
		slots = self.slots(session, day, start)
		return [r for r in rooms if not any((r, *slot) in self.room_busy for slot in slots)]

	def cost(self, session, day, start):
		maximum = self.grid.max_faculty_periods_per_day
		over = max(0, self.faculty_day[(session.faculty, day)] + session.length - maximum) if maximum else 0
		return (
			REPEAT_COST * self.course_day[self.course_key(session, day)]
			+ OVERLOAD_COST * over
			+ BALANCE_COST * self.section_day[(session.section, day)]
			+ LATE_COST * start
		)  # fmt: skip

	def options(self, session):
		"""(cost, order, (day, start, room)) of every open option, cheapest first."""
		rooms = self.eligible_rooms(session)
		found = []
		for d, day in enumerate(self.grid.days):
			for start in self.starts(session.length):
				if self.blocker(session, day, start):
					continue
				cost = self.cost(session, day, start)
				for r, room in enumerate(self.free_rooms(session, day, start, rooms)[:ROOM_TRIES]):
					found.append((cost + r * ROOM_RANK_COST, d * 1000 + start, (day, start, room)))
		return sorted(found)

	def best(self, session):
		options = self.options(session)
		return options[0][2] if options else None

	def explain(self, session):
		"""Why no slot is left for the session, counting the (day, start) options each constraint closed."""
		rooms = self.eligible_rooms(session)
		closed = Counter()
		total = 0
		for day in self.grid.days:
			for start in self.starts(session.length):
				total += 1
				reason = self.blocker(session, day, start) or ("room" if not self.free_rooms(session, day, start, rooms) else None)
				closed[reason] += 1
		return _(
			"{0} {1} ({2}): not placed by the search. Of {3} possible slots, {4} are closed because the teacher is unavailable, {5} because "
			"the teacher teaches elsewhere, {6} because the section has another class, {7} because no suitable room is free."
		).format(session.offering, _(session.kind), session.faculty, total, closed["unavailable"], closed["faculty"], closed["section"], closed["room"])  # fmt: skip

	# --- search --------------------------------------------------------------------------------

	def depth_first(self, order):
		"""Choices for a prefix of `order`: all of it when the search succeeds, else the deepest prefix reached."""
		n = len(order)
		frames, chosen, deepest, nodes = [], [], [], 0
		self.reset()
		i = 0
		while 0 <= i < n:
			if len(frames) == i:
				frames.append(iter(self.options(order[i])[: TRIES_PER_SESSION * ROOM_TRIES]))
			if len(chosen) > i:
				self.unplace(order[i], chosen.pop())
			nodes += 1
			if nodes > NODE_BUDGET or (nodes % 256 == 0 and time.monotonic() > self.deadline):
				break
			option = next(frames[i], None)
			if option is None:
				frames.pop()
				i -= 1
				continue
			self.place(order[i], option[2])
			chosen.append(option[2])
			i += 1
			if len(chosen) > len(deepest):
				deepest = list(chosen)
		return list(chosen) if i == n else deepest
