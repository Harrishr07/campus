"""M07-03 Publish a Timetable into education Course Schedules, so education's attendance works unchanged.

A Course Schedule is created for every grid row on each matching weekday from today (or the term start) to the term
end, marked with `oc_timetable`. Re-publishing replaces only the Course Schedules of that Timetable dated today or
later; earlier ones, other sources' schedules and any schedule that already has Student Attendance are never touched.
"""

import calendar

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, to_timedelta, today

from campus.faculty.timetable import context

QUEUE = "long"


@frappe.whitelist()
def publish_timetable(timetable):
	"""Check the grid and queue the publish; returns nothing (the Timetable turns Published when the job is done)."""
	doc = frappe.get_doc("Timetable", timetable)
	doc.check_permission("write")
	doc.check_hard_constraints()
	frappe.enqueue(
		"campus.faculty.timetable.publish.publish_now", queue=QUEUE, timeout=3600, now=frappe.in_test, enqueue_after_commit=True, timetable=timetable
	)


def publish_now(timetable, as_of=None):
	"""Replace the future Course Schedules of `timetable`; returns {"created", "removed", "kept"} counts."""
	frappe.db.get_value("Timetable", timetable, "name", for_update=True)  # one publish at a time
	doc = frappe.get_doc("Timetable", timetable)
	doc.check_hard_constraints()
	term = frappe.db.get_value("Academic Term", doc.academic_term, ["term_start_date", "term_end_date"], as_dict=True)
	start = max(getdate(as_of or today()), getdate(term.term_start_date))
	kept, removed = remove_future_schedules(doc.name, start)
	created = create_schedules(doc, start, getdate(term.term_end_date), kept)
	doc.db_set({"status": "Published", "published_on": now_datetime()}, update_modified=False)
	return {"created": created, "removed": removed, "kept": len(kept)}


def remove_future_schedules(timetable, start):
	"""Delete the timetable's unmarked schedules from `start`; returns ({(group, date, from_time)} of those kept, count deleted)."""
	schedules = frappe.get_all(
		"Course Schedule", {"oc_timetable": timetable, "schedule_date": [">=", start]}, ["name", "student_group", "schedule_date", "from_time"]
	)
	marked = set(frappe.get_all("Student Attendance", {"course_schedule": ["in", [s.name for s in schedules] or [""]]}, pluck="course_schedule"))
	kept, removed = set(), 0
	for schedule in schedules:
		if schedule.name in marked or not delete_schedule(schedule.name):
			kept.add(slot_key(schedule.student_group, schedule.schedule_date, schedule.from_time))
		else:
			removed += 1
	return kept, removed


def delete_schedule(name):
	try:
		frappe.delete_doc("Course Schedule", name, ignore_permissions=True)
	except frappe.LinkExistsError:
		return False  # something else points at it: keep it like a marked one
	return True


def slot_key(group, date, from_time):
	return (group, getdate(date), to_timedelta(from_time))


def create_schedules(timetable, start, end, kept):
	dates = weekday_dates(start, end)
	instructors = {}
	created = 0
	for row in timetable.entries:
		instructor = instructors.setdefault(row.faculty, frappe.db.get_value("Instructor", {"employee": row.faculty}))
		if not instructor:
			frappe.throw(_("{0} has no Instructor record, so cannot be scheduled.").format(row.faculty))
		for date in dates[row.day]:
			if slot_key(row.offering, date, row.from_time) in kept:
				continue
			new_schedule(timetable.name, row, instructor, date)
			created += 1
	return created


def weekday_dates(start, end):
	names = list(calendar.day_name)
	dates = {name: [] for name in names}
	day = start
	while day <= end:
		dates[names[day.weekday()]].append(day)
		day = add_days(day, 1)
	return dates


def new_schedule(timetable, row, instructor, date):
	group = frappe.db.get_value("Student Group", row.offering, ["course", "program"], as_dict=True)
	frappe.get_doc(
		{
			"doctype": "Course Schedule", "student_group": row.offering, "course": group.course, "program": group.program,
			"instructor": instructor, "room": row.room, "schedule_date": date, "from_time": row.from_time, "to_time": row.to_time,
			"oc_timetable": timetable,
		}
	).insert(ignore_permissions=True)  # fmt: skip
