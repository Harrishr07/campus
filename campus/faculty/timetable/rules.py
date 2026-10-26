"""M07-03 Timetable constraints, as pure functions on plain values (no database), so the solver, the Timetable
validator, the publish check and the clash checker report all judge a grid the same way.

Hard constraints (`violations`): no faculty, room or section in two places at once, classes only in teaching periods,
faculty unavailability, practicals in a lab and lectures outside labs, room capacity, and practical periods of a
course on a day consecutive in one room. Soft constraints (`soft_issues`): a course not repeated on a day, and no
more periods a day for a teacher than the template allows.
"""

from collections import Counter, defaultdict
from typing import NamedTuple

from frappe import _

FACULTY_CLASH = "Faculty clash"
ROOM_CLASH = "Room clash"
SECTION_CLASH = "Section clash"
INVALID_SLOT = "Invalid slot"
UNAVAILABLE = "Faculty unavailable"
LAB_ROOM = "Lab room"
CAPACITY = "Room capacity"
LAB_BLOCK = "Lab block"
SAME_DAY_REPEAT = "Course repeated on a day"
DAILY_MAXIMUM = "Faculty daily maximum"

PRACTICAL = "Practical"
KINDS = ("Lecture", "Tutorial", PRACTICAL)


class Entry(NamedTuple):
	"""One period of one class: `offering` (Student Group) of `section` taught by `faculty` in `room`."""

	offering: str
	section: str
	faculty: str
	room: str
	day: str
	period: int
	kind: str


class Room(NamedTuple):
	capacity: int
	is_lab: bool


class Grid(NamedTuple):
	"""The frame a timetable lives in. `periods` maps period number -> is_break; `unavailable` holds
	(faculty, day, period); `strengths` maps offering -> students."""

	days: list
	periods: dict
	rooms: dict
	strengths: dict
	unavailable: set
	lab_block: int
	max_faculty_periods_per_day: int


class Violation(NamedTuple):
	rule: str
	day: str
	period: int
	subject: str
	message: str


def teaching_periods(grid):
	return sorted(p for p, is_break in grid.periods.items() if not is_break)


def violations(entries, grid):
	"""Every hard-constraint breach of `entries` in `grid`."""
	found = invalid_slots(entries, grid)
	valid = [e for e in entries if not is_invalid(e, grid)]
	found += clashes(valid)
	found += [v for e in valid for v in entry_breaches(e, grid)]
	found += lab_block_breaches(valid, grid.lab_block)
	return found


def is_invalid(entry, grid):
	return entry.day not in grid.days or grid.periods.get(entry.period, True)


def invalid_slots(entries, grid):
	return [
		Violation(INVALID_SLOT, e.day, e.period, e.offering, _("{0}: {1} period {2} is not a teaching period of this template.").format(e.offering, e.day, e.period))
		for e in entries
		if is_invalid(e, grid)
	]  # fmt: skip


def clashes(entries):
	found = []
	for rule, key, label in (
		(FACULTY_CLASH, lambda e: e.faculty, _("{0} is in {1} classes on {2} period {3}")),
		(ROOM_CLASH, lambda e: e.room, _("Room {0} has {1} classes on {2} period {3}")),
		(SECTION_CLASH, lambda e: e.section, _("Section {0} has {1} classes on {2} period {3}")),
	):
		counts = Counter((key(e), e.day, e.period) for e in entries)
		found += [
			Violation(rule, day, period, subject, label.format(subject, count, day, period))
			for (subject, day, period), count in counts.items()
			if count > 1
		]  # fmt: skip
	return found


def entry_breaches(entry, grid):
	"""Unavailability, lab-versus-class room and capacity of one entry."""
	found = []
	if (entry.faculty, entry.day, entry.period) in grid.unavailable:
		found.append(Violation(UNAVAILABLE, entry.day, entry.period, entry.faculty,
			_("{0} is unavailable on {1} period {2}.").format(entry.faculty, entry.day, entry.period)))  # fmt: skip
	room = grid.rooms.get(entry.room)
	if not room:
		return found + [
			Violation(
				LAB_ROOM,
				entry.day,
				entry.period,
				entry.room,
				_("Room {0} is not available for timetabling.").format(entry.room),
			)
		]
	if (entry.kind == PRACTICAL) != room.is_lab:
		found.append(Violation(LAB_ROOM, entry.day, entry.period, entry.room,
			_("{0}: a {1} cannot be held in {2}; practicals need a lab and other classes a classroom.").format(entry.offering, _(entry.kind), entry.room)))  # fmt: skip
	strength = grid.strengths.get(entry.offering, 0)
	if room.capacity and strength > room.capacity:
		found.append(Violation(CAPACITY, entry.day, entry.period, entry.room,
			_("Room {0} seats {1} but {2} has {3} students.").format(entry.room, room.capacity, entry.offering, strength)))  # fmt: skip
	return found


def lab_block_breaches(entries, block):
	"""Practical periods of one course and teacher on a day must be consecutive, in one room and at most `block` long."""
	groups = defaultdict(list)
	for e in entries:
		if e.kind == PRACTICAL:
			groups[(e.offering, e.faculty, e.day)].append(e)
	found = []
	for (offering, _faculty, day), items in groups.items():
		periods = sorted(e.period for e in items)
		consecutive = periods == list(range(periods[0], periods[0] + len(periods)))
		if not consecutive or len({e.room for e in items}) > 1 or len(periods) > block:
			found.append(Violation(LAB_BLOCK, day, periods[0], offering,
				_("{0}: practical periods on {1} must be consecutive, in one lab and at most {3} long (periods {2}).").format(offering, day, ", ".join(map(str, periods)), block)))  # fmt: skip
	return found


def soft_issues(entries, grid):
	"""Soft-constraint breaches; a score for the solver and a warning for manual edits, never a block."""
	found = []
	repeats = Counter((e.offering, e.kind, e.day) for e in entries if e.kind != PRACTICAL)
	found += [
		Violation(SAME_DAY_REPEAT, day, 0, offering, _("{0} has {1} {2} periods on {3}.").format(offering, count, _(kind), day))
		for (offering, kind, day), count in repeats.items()
		if count > 1
	]  # fmt: skip
	load = Counter((e.faculty, e.day) for e in entries)
	maximum = grid.max_faculty_periods_per_day
	found += [
		Violation(DAILY_MAXIMUM, day, 0, faculty, _("{0} teaches {1} periods on {2}; the template maximum is {3}.").format(faculty, count, day, maximum))
		for (faculty, day), count in load.items()
		if maximum and count > maximum
	]  # fmt: skip
	return found
