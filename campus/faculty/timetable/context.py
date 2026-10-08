"""M07-03 Timetable data access: builds the pure `rules.Grid` and the solver `Problem` from the records (slot template,
rooms, student groups, submitted Course Allocations), and reads a Timetable's grid rows as `rules.Entry` values."""

import math

import frappe
from frappe import _
from frappe.utils import cint, flt

from campus.faculty.timetable.rules import PRACTICAL, Entry, Grid, Room
from campus.faculty.timetable.solver import DEFAULT_TIME_LIMIT, Problem, Session

LAB_TYPES = ("Lab", "Skill Lab")
NOT_TIMETABLED = ("Exam Hall",)


def entries_of(timetable):
	return [Entry(r.offering, r.section, r.faculty, r.room, r.day, cint(r.period), r.kind) for r in timetable.entries]


def build_grid(timetable):
	template = frappe.get_cached_doc("Timetable Slot Template", timetable.slot_template)
	offerings = {r.offering for r in timetable.entries}
	return Grid(
		days=[d.day for d in template.days],
		periods={p.period: bool(p.is_break) for p in template.periods},
		rooms=rooms_of(timetable.company),
		strengths=strengths_of(offerings),
		unavailable=unavailable_of(timetable, [p.period for p in template.periods if not p.is_break]),
		lab_block=cint(template.lab_block_periods) or 1,
		max_faculty_periods_per_day=cint(template.max_faculty_periods_per_day),
	)


def rooms_of(company):
	"""Rooms of the company by name; a room without a type counts as a classroom."""
	rooms = frappe.get_all("Room", {"oc_company": company}, ["name", "seating_capacity", "oc_room_type"])
	return {r.name: Room(cint(r.seating_capacity), r.oc_room_type in LAB_TYPES) for r in rooms if r.oc_room_type not in NOT_TIMETABLED}


def strengths_of(offerings):
	"""Students of each offering: the active ones in the group, else the group's maximum strength."""
	if not offerings:
		return {}
	limits = dict(frappe.get_all("Student Group", {"name": ["in", list(offerings)]}, ["name", "max_strength"], as_list=True))
	counts = dict(
		frappe.get_all(
			"Student Group Student", {"parent": ["in", list(offerings)], "active": 1}, ["parent", {"COUNT": "name"}], group_by="parent", as_list=True
		)
	)
	return {o: cint(counts.get(o)) or cint(limits.get(o)) for o in offerings}


def unavailable_of(timetable, teaching):
	"""{(faculty, day, period)}: a row with period 0 closes every teaching period of its day."""
	blocked = set()
	for row in timetable.unavailability:
		periods = [cint(row.period)] if cint(row.period) else teaching
		blocked.update((row.faculty, row.day, p) for p in periods)
	return blocked


def complete_entries(timetable):
	"""Fill each grid row's section and clock times from its offering and period; refuse offerings of another term."""
	template = frappe.get_cached_doc("Timetable Slot Template", timetable.slot_template)
	times = {p.period: (p.from_time, p.to_time) for p in template.periods}
	for row in timetable.entries:
		group = frappe.db.get_value("Student Group", row.offering, ["academic_term", "program", "oc_semester", "oc_section"], as_dict=True)
		if not group or group.academic_term != timetable.academic_term:
			frappe.throw(_("Row {0}: {1} is not a course offering of {2}.").format(row.idx, row.offering, timetable.academic_term))
		row.section = section_of(row.offering, group)
		row.from_time, row.to_time = times.get(cint(row.period), (None, None))


def section_of(offering, group):
	"""The students who attend together: program, semester and section; an offering without a section stands alone."""
	if not group.oc_section:
		return offering
	return f"{group.program} S{group.oc_semester or '-'} {group.oc_section}"


def allocation_rows(timetable):
	filters = {"company": timetable.company, "academic_term": timetable.academic_term, "docstatus": 1}
	if timetable.department:
		filters["department"] = timetable.department
	allocations = frappe.get_all("Course Allocation", filters, pluck="name")
	if not allocations:
		frappe.throw(_("No submitted Course Allocation for {0} in {1}.").format(timetable.academic_term, timetable.department or timetable.company))
	return frappe.get_all(
		"Course Allocation Row", {"parent": ["in", allocations]},
		["offering", "faculty", "lecture_hours", "tutorial_hours", "practical_hours"], order_by="parent, idx",
	)  # fmt: skip


def sessions_of(timetable, grid):
	"""One Session per class to place: a lecture or tutorial period each, a practical hour block of `lab_block` periods."""
	rows = allocation_rows(timetable)
	groups = {
		g.name: g
		for g in frappe.get_all("Student Group", {"name": ["in", list({r.offering for r in rows})]}, ["name", "program", "oc_semester", "oc_section"])
	}
	strengths = strengths_of(set(groups))
	sessions = []
	for row in rows:
		section = section_of(row.offering, groups[row.offering])
		shapes = (
			[("Lecture", 1)] * math.ceil(flt(row.lecture_hours))
			+ [("Tutorial", 1)] * math.ceil(flt(row.tutorial_hours))
			+ practical_blocks(math.ceil(flt(row.practical_hours)), grid.lab_block)
		)
		sessions += [Session(len(sessions) + i, row.offering, section, row.faculty, kind, length, strengths[row.offering]) for i, (kind, length) in enumerate(shapes)]
	return sessions


def practical_blocks(hours, block):
	"""Practical hours as blocks of `block` consecutive periods, the remainder as one shorter block."""
	blocks = [(PRACTICAL, block)] * (hours // block)
	return blocks + ([(PRACTICAL, hours % block)] if hours % block else [])


def build_problem(timetable, time_limit=DEFAULT_TIME_LIMIT):
	"""The solver's input. The grid is built from the rooms and strengths of the offerings to place, not the current rows."""
	template = frappe.get_cached_doc("Timetable Slot Template", timetable.slot_template)
	grid = build_grid(timetable)._replace(strengths={})
	sessions = sessions_of(timetable, grid)
	grid = grid._replace(strengths={s.offering: s.strength for s in sessions})
	return Problem(grid=grid, sessions=sessions, time_limit=time_limit or DEFAULT_TIME_LIMIT), template


def as_rows(entries, template):
	times = {p.period: (p.from_time, p.to_time) for p in template.periods}
	return [
		{
			"offering": e.offering, "section": e.section, "kind": e.kind, "faculty": e.faculty, "room": e.room, "day": e.day,
			"period": e.period, "from_time": times[e.period][0], "to_time": times[e.period][1],
		}
		for e in entries
	]  # fmt: skip


