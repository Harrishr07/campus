"""M06-02 Invigilation roster algorithm (pure: no frappe, no DB).

Halls are staffed in date, slot (FN before AN), room order. Each place goes to the faculty member with the fewest
duties of that slot type so far, then the fewest duties in all, then the lowest id, among those who are not on
leave that day, not already in another hall of the sitting, and do not teach a course written in the hall.
That keeps duties within one per faculty per session type unless the exclusions force otherwise.
A place nobody may take is returned unfilled.
"""

from collections import Counter, namedtuple

Hall = namedtuple("Hall", "date slot room courses")
SLOT_ORDER = {"FN": 0, "AN": 1}


def assign(halls, faculty, own_courses=None, on_leave=(), per_hall=1):
	"""([(Hall, employee)], [Hall unfilled]) ; `own_courses` {employee: courses}, `on_leave` {(employee, date)}."""
	own_courses, on_leave = own_courses or {}, set(on_leave)
	by_slot, total, busy = Counter(), Counter(), set()
	duties, unfilled = [], []
	for hall in sorted(halls, key=lambda h: (str(h.date), SLOT_ORDER.get(h.slot, 9), h.slot, h.room)):
		for _place in range(per_hall):
			free = [
				e for e in faculty
				if (e, str(hall.date)) not in on_leave
				and (e, str(hall.date), hall.slot) not in busy
				and not set(own_courses.get(e, ())) & set(hall.courses)
			]  # fmt: skip
			if not free:
				unfilled.append(hall)
				continue
			chosen = min(free, key=lambda e: (by_slot[e, hall.slot], total[e], e))
			by_slot[chosen, hall.slot] += 1
			total[chosen] += 1
			busy.add((chosen, str(hall.date), hall.slot))
			duties.append((hall, chosen))
	return duties, unfilled
