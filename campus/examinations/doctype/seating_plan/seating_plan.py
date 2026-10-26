"""M06-02 Seating Plan: the seats of one date and slot of an Exam Session, and its exam attendance.

The seats are server-owned: only the generator (campus.examinations.seating) writes them; a hand edit may only
mark a student absent. Changing the halls clears the seats until the plan is generated again. Halls must be Exam Halls of the session's company with a seat layout.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from campus.examinations import exam_halls
from campus.examinations.seating import plan_name

SEAT_FIELDS = ("room", "seat_row", "seat_column", "student", "course")


class SeatingPlan(Document):
	def autoname(self):
		self.name = plan_name(self.exam_session, self.exam_date, self.slot)

	def validate(self):
		session = frappe.db.get_value("Exam Session", self.exam_session, ["company", "status"], as_dict=True)
		if session.status == "Published":
			frappe.throw(
				_("The results of {0} are published; its seating and attendance are closed.").format(
					self.exam_session
				)
			)
		self.company = session.company
		self.validate_halls()
		self.guard_seats()
		self.set_counts()

	def validate_halls(self):
		seen = set()
		for hall in self.halls:
			if hall.room in seen:
				frappe.throw(
					_("Row {0}: {1} is already in the plan.").format(hall.idx, frappe.bold(hall.room))
				)
			seen.add(hall.room)
			if frappe.db.get_value("Room", hall.room, "oc_company") != self.company:
				frappe.throw(
					_("Row {0}: {1} does not belong to {2}.").format(
						hall.idx, frappe.bold(hall.room), self.company
					)
				)
			grid = exam_halls.layout(hall.room)
			if not grid:
				frappe.throw(
					_("Row {0}: {1} is not an Exam Hall with seat rows and columns.").format(
						hall.idx, frappe.bold(hall.room)
					)
				)
			rows, columns, blocked = grid
			hall.seat_rows, hall.seat_columns, hall.capacity = rows, columns, rows * columns - len(blocked)

	def guard_seats(self):
		if self.flags.generating:
			return
		before = self.get_doc_before_save()
		if before and {h.room for h in before.halls} != {h.room for h in self.halls} and self.seats:
			if any(seat.absent for seat in self.seats):
				frappe.throw(_("Attendance is already marked; the halls of this plan cannot change."))
			self.set("seats", [])  # the old seats no longer fit the halls: Generate Seating again
			return
		old = {seat_key(s) for s in before.seats} if before else set()
		if {seat_key(s) for s in self.seats} != old:
			frappe.throw(_("Seats are set by Generate Seating; only the absent mark can be changed by hand."))

	def set_counts(self):
		for hall in self.halls:
			hall.seated = sum(1 for seat in self.seats if seat.room == hall.room)
		self.seated = len(self.seats)


def seat_key(seat):
	return tuple(seat.get(f) for f in SEAT_FIELDS)
