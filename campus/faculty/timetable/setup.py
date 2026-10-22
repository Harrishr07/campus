"""M07-03, M05-12 Timetable setup: Room fields (blueprint 9.8, reusing education Room, no new room master), the link from
a Course Schedule back to the Timetable that published it, and the class session state of a Course Schedule."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from campus.student_services.attendance_rules import MAKEUP, RESCHEDULED, SCHEDULED, SESSION_STATES

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
		},
		*session_fields(),
	]  # fmt: skip


def session_fields():
	"""M05-12 Session state: only held sessions count towards attendance (campus.student_services.attendance_rules)."""
	return [
		{
			"fieldname": "oc_session_state", "label": "Session State", "fieldtype": "Select", "options": "\n".join(SESSION_STATES),
			"default": SCHEDULED, "insert_after": "oc_timetable", "in_list_view": 1, "in_standard_filter": 1, "no_copy": 1,
			"module": "Faculty", "description": "Marking attendance makes a Scheduled session Conducted. Cancelled and Rescheduled sessions do not count.",
		},
		{
			"fieldname": "oc_rescheduled_to", "label": "Rescheduled To", "fieldtype": "Link", "options": "Course Schedule",
			"insert_after": "oc_session_state", "no_copy": 1, "depends_on": f"eval:doc.oc_session_state=='{RESCHEDULED}'",
			"mandatory_depends_on": f"eval:doc.oc_session_state=='{RESCHEDULED}'", "module": "Faculty",
			"description": "The session this one moved to; it counts on its own date.",
		},
		{
			"fieldname": "oc_makeup_for", "label": "Makeup For", "fieldtype": "Link", "options": "Course Schedule",
			"insert_after": "oc_rescheduled_to", "no_copy": 1, "search_index": 1, "depends_on": f"eval:doc.oc_session_state=='{MAKEUP}'",
			"mandatory_depends_on": f"eval:doc.oc_session_state=='{MAKEUP}'", "module": "Faculty",
			"description": "The session this makeup replaces; the replaced session no longer counts.",
		},
		{
			"fieldname": "oc_state_reason", "label": "State Change Reason", "fieldtype": "Small Text", "insert_after": "oc_makeup_for",
			"no_copy": 1, "module": "Faculty", "description": "Needed to change the state once attendance is marked; the change is logged.",
		},
	]  # fmt: skip
