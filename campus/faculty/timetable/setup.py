"""M07-03 Timetable setup: Room fields (blueprint 9.8, reusing education Room, no new room master) and the link from
a Course Schedule back to the Timetable that published it."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ROOM_TYPES = ["Classroom", "Lab", "Seminar Hall", "Skill Lab", "Exam Hall"]


def setup_timetable():
	create_custom_fields({"Room": room_fields(), "Course Schedule": schedule_fields()}, update=True)


def room_fields():
	return [
		{
			"fieldname": "oc_room_type", "label": "Room Type", "fieldtype": "Select", "options": "\n".join(ROOM_TYPES),
			"default": "Classroom", "insert_after": "room_number", "in_list_view": 1, "in_standard_filter": 1, "module": "Faculty",
			"description": "Labs and Skill Labs host practicals; Exam Halls are not timetabled. Seating Capacity is the room's capacity.",
		}
	]  # fmt: skip


def schedule_fields():
	return [
		{
			"fieldname": "oc_timetable", "label": "Timetable", "fieldtype": "Link", "options": "Timetable", "insert_after": "room",
			"read_only": 1, "no_copy": 1, "search_index": 1, "module": "Faculty",
		}
	]  # fmt: skip
