"""M06-02 Seating plan algorithm (pure: no frappe, no DB).

Seats are filled hall by hall, row by row. Each seat takes the course with the most students left that differs
from the course in front of it and to its left; ties go to the course name, and a course's students are seated
in id order, so the plan does not depend on the input order. When no course fits and there are spare seats the
seat stays empty; with no spare seat left the largest course is seated anyway. A repair pass then swaps seats (in
seat order) while a swap lowers the number of clashes, which fixes the clashes the greedy fill walks into when
the mix allows. Neighbours are row/column neighbours of the same hall. More students than seats is refused.
"""

from collections import namedtuple

Seat = namedtuple("Seat", "hall row column")


class CapacityError(ValueError):
	pass


def hall_seats(hall, rows, columns, blocked=()):
	"""The usable seats of one hall, row by row; `blocked` holds (row, column) pairs."""
	blocked = set(blocked)
	return [
		Seat(hall, row, column)
		for row in range(1, rows + 1)
		for column in range(1, columns + 1)
		if (row, column) not in blocked
	]


def assign(seats, candidates):
	"""{Seat: (student, course) or None} for every seat; `candidates` is [(student, course)]."""
	if len(candidates) > len(seats):
		raise CapacityError(f"{len(candidates)} students for {len(seats)} seats")
	queues = course_queues(candidates)
	spare, plan = len(seats) - len(candidates), {}
	for seat in seats:
		course = next_course(queues, neighbour_courses(plan, seat), spare)
		if course is None:
			plan[seat] = None
			spare -= any(queues.values())  # an empty seat left while students wait uses up a spare one
			continue
		plan[seat] = (queues[course].pop(0), course)
	repair(plan, seats)
	return plan


def conflicts(plan):
	"""The number of row/column neighbour pairs of one hall that share a course."""
	courses = {seat: candidate[1] for seat, candidate in plan.items() if candidate}
	return sum(
		courses.get(Seat(seat.hall, seat.row + dr, seat.column + dc)) == course
		for seat, course in courses.items()
		for dr, dc in ((0, 1), (1, 0))
	)


def repair(plan, seats):
	"""Swap clashing seats with others while a swap lowers the clash count; ends as each swap removes one or more."""
	improved = True
	while improved:
		improved = False
		for seat in seats:
			if plan[seat] and clashes_at(plan, seat) and swap_away(plan, seat, seats):
				improved = True


def swap_away(plan, seat, seats):
	for other in seats:
		if other == seat or (plan[other] and plan[other][1] == plan[seat][1]):
			continue
		before = clashes_at(plan, seat) + clashes_at(plan, other)
		plan[seat], plan[other] = plan[other], plan[seat]
		if clashes_at(plan, seat) + clashes_at(plan, other) < before:
			return True
		plan[seat], plan[other] = plan[other], plan[seat]
	return False


def clashes_at(plan, seat):
	"""Neighbours of `seat` (all four sides) that share its course."""
	if not plan.get(seat):
		return 0
	course = plan[seat][1]
	near = ((-1, 0), (1, 0), (0, -1), (0, 1))
	return sum(
		bool(plan.get(Seat(seat.hall, seat.row + dr, seat.column + dc)))
		and plan[Seat(seat.hall, seat.row + dr, seat.column + dc)][1] == course
		for dr, dc in near
	)


def course_queues(candidates):
	queues = {}
	for student, course in sorted(candidates):
		queues.setdefault(course, []).append(student)
	return queues


def neighbour_courses(plan, seat):
	near = (Seat(seat.hall, seat.row - 1, seat.column), Seat(seat.hall, seat.row, seat.column - 1))
	return {plan[s][1] for s in near if plan.get(s)}


def next_course(queues, avoid, spare):
	"""The course for the next seat, or None to leave it empty."""
	waiting = [course for course, queue in queues.items() if queue]
	allowed = [course for course in waiting if course not in avoid]
	if allowed:
		return largest(queues, allowed)
	if not waiting or spare > 0:
		return None
	return largest(queues, waiting)


def largest(queues, courses):
	return min(courses, key=lambda course: (-len(queues[course]), course))
