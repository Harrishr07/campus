"""M06-02 Invigilation roster algorithm (pure: no frappe, no DB).

Within each session type (FN, then AN) the most-constrained places are staffed first: those the fewest faculty
may take (not on leave that day, not teaching a course written in the hall), then by date and room. Each place
goes to the eligible faculty member with the fewest duties of that session type so far, then the fewest in all,
then the lowest id, who is not already in another hall of the same sitting. A rebalancing pass then moves a duty
from a faculty member to one with at least two fewer of that session type who may take it and is free in that
sitting, while such a move exists (each move lowers the sum of squared loads, so it ends). That keeps duties
within one per faculty per session type unless the exclusions force otherwise; `spread` reports the gap so the
caller can warn. A place nobody may take is returned unfilled.
"""

from collections import Counter, namedtuple

Hall = namedtuple("Hall", "date slot room courses")
SLOT_ORDER = {"FN": 0, "AN": 1}


def assign(halls, faculty, own_courses=None, on_leave=(), per_hall=1):
	"""([(Hall, employee)], [Hall unfilled]) in date/slot/room order; `own_courses` {employee: courses},
	`on_leave` {(employee, date)}."""
	own_courses, on_leave, faculty = own_courses or {}, set(on_leave), sorted(faculty)

	def eligible(hall):
		return [
			e for e in faculty
			if (e, str(hall.date)) not in on_leave and not set(own_courses.get(e, ())) & set(hall.courses)
		]  # fmt: skip

	places = [(hall, eligible(hall)) for hall in halls for _place in range(per_hall)]
	places.sort(key=lambda p: (slot_rank(p[0].slot), len(p[1]), sitting_key(p[0])))
	by_slot, total, busy = Counter(), Counter(), set()
	duties, unfilled = [], []
	for hall, people in places:
		free = [e for e in people if (e, str(hall.date), hall.slot) not in busy]
		if not free:
			unfilled.append(hall)
			continue
		chosen = min(free, key=lambda e: (by_slot[e, hall.slot], total[e], e))
		by_slot[chosen, hall.slot] += 1
		total[chosen] += 1
		busy.add((chosen, str(hall.date), hall.slot))
		duties.append([hall, chosen, people])
	duties.sort(key=lambda d: (sitting_key(d[0]), d[1]))
	rebalance(duties, by_slot, busy)
	return sorted(((h, e) for h, e, _p in duties), key=lambda d: (sitting_key(d[0]), d[1])), sorted(unfilled, key=sitting_key)


def rebalance(duties, by_slot, busy):
	"""Move single duties from heavier to lighter (by two or more) eligible, free faculty until none can move."""
	moved = True
	while moved:
		moved = False
		for duty in duties:
			hall, holder, people = duty
			sitting = (str(hall.date), hall.slot)
			lighter = [
				e for e in people
				if by_slot[holder, hall.slot] - by_slot[e, hall.slot] >= 2 and (e, *sitting) not in busy
			]  # fmt: skip
			if not lighter:
				continue
			taker = min(lighter, key=lambda e: (by_slot[e, hall.slot], e))
			busy.discard((holder, *sitting))
			busy.add((taker, *sitting))
			by_slot[holder, hall.slot] -= 1
			by_slot[taker, hall.slot] += 1
			duty[1], moved = taker, True


def spread(duties, faculty):
	"""{session type: most duties - fewest duties} over all `faculty`, for each session type with duties."""
	counts = Counter((hall.slot, employee) for hall, employee in duties)
	return {
		slot: max(counts[slot, e] for e in faculty) - min(counts[slot, e] for e in faculty)
		for slot in sorted({hall.slot for hall, _e in duties}, key=slot_rank)
	}


def slot_rank(slot):
	return (SLOT_ORDER.get(slot, 9), slot)


def sitting_key(hall):
	return (str(hall.date), slot_rank(hall.slot), hall.room)
