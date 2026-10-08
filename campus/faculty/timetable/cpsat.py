"""M07-03 CP-SAT timetable backend (OR-Tools), used by `solver.solve` whenever ortools imports.

One boolean per (session, day, start period, room) that respects the static rules (teaching run, faculty availability,
room kind and capacity). Hard constraints: a session is placed at most once; a teacher, room or section is in one place per
period; a course's practical block is on one day at most. The objective maximises sessions placed (a large weight), then
minimises the soft costs (course repeated on a day, teacher over the daily maximum, late periods).

Honest reporting: when the optimum places fewer sessions than asked, no complete timetable exists, so the result is
"infeasible" (proven); when the time limit stops the search first the best timetable found is returned as "feasible".
"""

import time
from collections import defaultdict
from dataclasses import replace

from frappe import _
from ortools.sat.python import cp_model

from campus.faculty.timetable import backtracking, rules
from campus.faculty.timetable.rules import PRACTICAL, Entry
from campus.faculty.timetable.solver import Result

PRESOLVE_LIMIT = 50_000
WARM_START_SHARE, WARM_START_CAP, MIN_SOLVE_SECONDS = 0.1, 15, 0.5
REPEAT_COST, OVERLOAD_COST, LATE_COST = 100, 200, 1


def solve(problem):
	"""One time budget (`problem.time_limit`): the warm-start search gets a tenth of it (at most WARM_START_CAP seconds),
	model building and CP-SAT use the rest. If CP-SAT has no time left or finds nothing, the warm start is the answer."""
	started = time.monotonic()
	warm = backtracking.solve(replace(problem, time_limit=min(WARM_START_CAP, problem.time_limit * WARM_START_SHARE)))
	search = backtracking.Search(problem)
	unmet = search.pre_check()
	sessions = [s for s in problem.sessions if s.id not in search.hopeless]
	model, variables = build_model(problem, search, sessions)
	remaining = problem.time_limit - (time.monotonic() - started)
	if remaining < MIN_SOLVE_SECONDS:
		return warm
	hint(model, variables, warm)  # CP-SAT never returns less than the search found
	solver = cp_model.CpSolver()
	solver.parameters.max_time_in_seconds = remaining
	solver.parameters.num_workers = 8
	solver.parameters.cp_model_presolve = len(variables) < PRESOLVE_LIMIT  # on a big model presolve alone can eat the budget
	status = solver.Solve(model)
	if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
		return warm
	chosen = {sid: (day, start, room) for (sid, day, start, room), var in variables.items() if solver.BooleanValue(var)}
	by_id = {s.id: s for s in sessions}
	search.restore({sid: (by_id[sid], choice) for sid, choice in chosen.items()})
	missing = [s for s in sessions if s.id not in chosen]
	unmet += [search.explain(s) for s in missing]
	entries = sorted(search.entries(), key=lambda e: (e.section, e.day, e.period, e.offering))
	complete = not unmet
	if complete:
		verdict = "optimal" if status == cp_model.OPTIMAL else "feasible"
	else:
		verdict = "infeasible" if status == cp_model.OPTIMAL or search.hopeless else "feasible"
	if verdict == "infeasible":
		unmet.insert(0, _("CP-SAT proved that no timetable can place every class under the hard constraints; the most classes that fit are placed."))
	elif missing:
		unmet.insert(0, _("The time limit stopped CP-SAT before it could place every class; this is the best timetable found, not a proof of infeasibility."))
	return Result(entries, unmet, len(rules.soft_issues(entries, problem.grid)), status=verdict, backend="cpsat", unplaced=len(search.hopeless) + len(missing), placements=chosen)


def hint(model, variables, found):
	"""Warm start from the search's timetable: its choices are 1, every other option 0."""
	chosen = {(sid, *choice) for sid, choice in found.placements.items()}
	for key, var in variables.items():
		model.AddHint(var, 1 if key in chosen else 0)


def build_model(problem, search, sessions):
	grid = problem.grid
	model = cp_model.CpModel()
	variables = {}
	faculty_slot, room_slot, section_slot = defaultdict(list), defaultdict(list), defaultdict(list)
	course_day, practical_day, faculty_day = defaultdict(list), defaultdict(list), defaultdict(list)
	late, worst = [], 0  # worst: the largest total soft cost any timetable can have
	for s in sessions:
		options = []
		for day in grid.days:
			for start in search.starts(s.length):
				slots = search.slots(s, day, start)
				if any((s.faculty, day, p) in grid.unavailable for _d, p in slots):
					continue
				for room in search.eligible_rooms(s):
					var = model.NewBoolVar(f"x{s.id}_{day}_{start}_{room}")
					variables[(s.id, day, start, room)] = var
					options.append(var)
					for _d, p in slots:
						faculty_slot[(s.faculty, day, p)].append(var)
						room_slot[(room, day, p)].append(var)
						section_slot[(s.section, day, p)].append(var)
					key = (s.offering, s.faculty, day) if s.kind == PRACTICAL else (s.offering, s.kind, day)
					(practical_day if s.kind == PRACTICAL else course_day)[key].append(var)
					faculty_day[(s.faculty, day)].append((s.length, var))
					late.append(LATE_COST * start * var)
		worst += LATE_COST * max(search.starts(s.length), default=0)
		model.AddAtMostOne(options)
	for group in (faculty_slot, room_slot, section_slot, practical_day):
		for vars_ in group.values():
			model.AddAtMostOne(vars_)
	penalties = list(late)
	for vars_ in course_day.values():
		repeat = model.NewIntVar(0, len(vars_), "repeat")
		model.Add(repeat >= sum(vars_) - 1)
		penalties.append(REPEAT_COST * repeat)
		worst += REPEAT_COST * len(vars_)
	maximum = grid.max_faculty_periods_per_day
	for items in faculty_day.values() if maximum else []:
		over = model.NewIntVar(0, sum(length for length, _v in items), "over")
		model.Add(over >= sum(length * v for length, v in items) - maximum)
		penalties.append(OVERLOAD_COST * over)
		worst += OVERLOAD_COST * sum(length for length, _v in items)
	model.Maximize((1 + worst) * sum(variables.values()) - sum(penalties))  # one true variable per placed session; one more class always outweighs every soft cost, so a shortfall proven optimal is real
	return model, variables
