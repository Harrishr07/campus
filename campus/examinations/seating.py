"""M06-02 Seating plans and exam attendance.

A Seating Plan seats, for one date and slot of an Exam Session, every student holding an Issued Hall Ticket
with a course on that date and slot, in the plan's Exam Halls (seating_rules: courses interleaved, blocked seats
skipped, capacity never exceeded, deterministic). Exam attendance is the seat's `absent` mark; the Result Run
reads it (`absent`) and grades the course AB.
"""

import frappe
from frappe import _
from frappe.utils import cint, formatdate

from campus.examinations import exam_halls, seating_rules
from campus.examinations.access import COE_ROLE

DOCTYPE, SEAT = "Seating Plan", "Seating Plan Seat"


def plan_name(exam_session, exam_date, slot):
	return f"SP-{exam_session}-{exam_date}-{slot}"


def generate(seating_plan):
	"""(Re)seat the plan; refused once attendance is marked. Returns the number seated."""
	frappe.only_for((COE_ROLE, "System Manager"))
	plan = frappe.get_doc(DOCTYPE, seating_plan, for_update=True)
	plan.check_permission("write")
	if any(seat.absent for seat in plan.seats):
		frappe.throw(_("Attendance is already marked on {0}; it cannot be re-seated.").format(plan.name))
	seats = hall_seats(plan)
	candidates = candidates_of(plan.exam_session, plan.exam_date, plan.slot)
	try:
		placed = seating_rules.assign(seats, [(c.student, c.course) for c in candidates])
	except seating_rules.CapacityError:
		frappe.throw(
			_("{0} students write on {1} {2} but the halls seat {3}. Add an Exam Hall.").format(
				len(candidates), formatdate(plan.exam_date), plan.slot, len(seats)
			)
		)
	names = {c.student: c.student_name for c in candidates}
	plan.set("seats", [seat_row(seat, taken, names) for seat, taken in placed.items() if taken])
	plan.adjacent_same_course = seating_rules.conflicts(placed)
	plan.flags.generating = True
	plan.save()
	return len(plan.seats)


def mark_absent(seating_plan, students, value=1):
	"""Mark (value 1) or clear (0) the listed students absent on the plan; returns the number of seats changed."""
	frappe.only_for((COE_ROLE, "System Manager"))
	plan = frappe.get_doc(DOCTYPE, seating_plan, for_update=True)
	plan.check_permission("write")
	wanted, value, changed = set(frappe.parse_json(students) if isinstance(students, str) else students), cint(value), 0
	for seat in plan.seats:
		if seat.student in wanted and seat.absent != value:
			seat.absent, changed = value, changed + 1
	plan.save()
	return changed


def absent(student, exam_session, course):
	"""True when the student is marked absent for `course` in a Seating Plan of the session (one query)."""
	plan, seat = frappe.qb.DocType(DOCTYPE), frappe.qb.DocType(SEAT)
	return bool(
		frappe.qb.from_(seat)
		.join(plan).on(plan.name == seat.parent)
		.select(seat.name)
		.where(
			(seat.parenttype == DOCTYPE) & (plan.exam_session == exam_session) & (seat.student == student)
			& (seat.course == course) & (seat.absent == 1)
		)
		.limit(1)
		.run()
	)  # fmt: skip


def hall_seats(plan):
	seats = []
	for hall in plan.halls:
		grid = exam_halls.layout(hall.room)
		if not grid:  # the room lost its layout or Exam Hall type after the plan was saved
			frappe.throw(_("{0} is not an Exam Hall with seat rows and columns.").format(frappe.bold(hall.room)))
		seats += seating_rules.hall_seats(hall.room, *grid)
	return seats


def candidates_of(exam_session, exam_date, slot):
	"""Students with an Issued Hall Ticket listing a course on that date and slot: [{student, student_name, course}]."""
	ticket, course = frappe.qb.DocType("Hall Ticket"), frappe.qb.DocType("Hall Ticket Course")
	return (
		frappe.qb.from_(course)
		.join(ticket).on(ticket.name == course.parent)
		.select(ticket.student, ticket.student_name, course.course)
		.where(
			(course.parenttype == "Hall Ticket") & (ticket.exam_session == exam_session) & (ticket.status == "Issued")
			& (course.exam_date == exam_date) & (course.slot == slot)
		)
		.orderby(ticket.student).orderby(course.course)
		.run(as_dict=True)
	)  # fmt: skip


def seat_row(seat, taken, names):
	student, course = taken
	return {
		"room": seat.hall, "seat_row": seat.row, "seat_column": seat.column,
		"seat_label": exam_halls.seat_label(seat.row, seat.column),
		"student": student, "student_name": names.get(student), "course": course,
	}  # fmt: skip
