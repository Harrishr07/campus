"""M06-02 Exam Hall: an education Room with Room Type "Exam Hall" (T07's oc_room_type, no hall master) and a
seat layout of rows x columns with blocked seats. The usable seats (grid minus blocked) are the hall's
Seating Capacity, so a seating plan can never put more students in it.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint

EXAM_HALL = "Exam Hall"
IS_HALL = 'eval:doc.oc_room_type=="Exam Hall"'


def setup_exam_halls():
	create_custom_fields({"Room": room_fields()}, update=True)


def room_fields():
	return [
		{"fieldname": "oc_seat_rows", "label": "Seat Rows", "fieldtype": "Int", "insert_after": "oc_room_type", "depends_on": IS_HALL, "non_negative": 1, "module": "Examinations"},
		{"fieldname": "oc_seat_columns", "label": "Seat Columns", "fieldtype": "Int", "insert_after": "oc_seat_rows", "depends_on": IS_HALL, "non_negative": 1, "module": "Examinations"},
		{
			"fieldname": "oc_blocked_seats", "label": "Blocked Seats", "fieldtype": "Table", "options": "Exam Hall Blocked Seat",
			"insert_after": "oc_seat_columns", "depends_on": IS_HALL, "module": "Examinations",
			"description": "Seats never used in a seating plan (pillar, broken bench). Seating Capacity becomes rows x columns minus these.",
		},
	]  # fmt: skip


def validate_room(doc, method=None):
	"""Room validate: an Exam Hall with a layout keeps its blocked seats inside the grid and its capacity in step."""
	if doc.get("oc_room_type") != EXAM_HALL or not (
		cint(doc.get("oc_seat_rows")) and cint(doc.get("oc_seat_columns"))
	):
		return
	rows, columns, seen = cint(doc.oc_seat_rows), cint(doc.oc_seat_columns), set()
	for seat in doc.get("oc_blocked_seats") or []:
		position = (cint(seat.seat_row), cint(seat.seat_column))
		if not (1 <= position[0] <= rows and 1 <= position[1] <= columns):
			frappe.throw(
				_("Blocked seat {0} is outside the {1} x {2} layout.").format(
					seat_label(*position), rows, columns
				)
			)
		if position in seen:
			frappe.throw(_("Blocked seat {0} is listed twice.").format(seat_label(*position)))
		seen.add(position)
	doc.seating_capacity = str(rows * columns - len(seen))


def layout(room):
	"""(rows, columns, {(row, column) blocked}) of an Exam Hall, or None when the room is not one with a layout."""
	values = frappe.db.get_value(
		"Room", room, ["oc_room_type", "oc_seat_rows", "oc_seat_columns"], as_dict=True
	)
	if not values or values.oc_room_type != EXAM_HALL or not (values.oc_seat_rows and values.oc_seat_columns):
		return None
	blocked = frappe.get_all(
		"Exam Hall Blocked Seat", {"parent": room, "parenttype": "Room"}, ["seat_row", "seat_column"]
	)
	return values.oc_seat_rows, values.oc_seat_columns, {(b.seat_row, b.seat_column) for b in blocked}


def seat_label(row, column):
	return f"R{row}C{column}"
