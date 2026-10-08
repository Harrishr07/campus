"""M07-03 Publish a Timetable into education Course Schedules, so education's attendance works unchanged.

A Course Schedule is created for every grid row on each matching weekday from today (or the term start) to the term
end, marked with `oc_timetable`. Re-publishing replaces only the Course Schedules of that Timetable dated today or
later; earlier ones, other sources' schedules and any schedule that already has Student Attendance are never touched.

Publishing is checked before anything is deleted (`preflight`): the grid is clash-free, every teacher has an Instructor
record, and no teacher or room is double-booked against another published Timetable of the company and term. A failed
job rolls back and records the reason on the Timetable (`publish_state`, `publish_error`).
"""

import calendar

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, to_timedelta, today

QUEUE = "long"
SAVEPOINT = "timetable_publish"
PUBLISHED = ("Published", "Changed since publish")


@frappe.whitelist()
def publish_timetable(timetable):
	"""Check the grid and queue the publish; the Timetable turns Published when the job is done."""
	doc = frappe.get_doc("Timetable", timetable)
	doc.check_permission("write")
	preflight(doc)
	frappe.db.set_value("Timetable", timetable, {"publish_state": "Queued", "publish_error": None}, update_modified=False)
	frappe.enqueue(
		"campus.faculty.timetable.publish.publish_job", queue=QUEUE, timeout=3600, now=frappe.in_test, enqueue_after_commit=True, timetable=timetable
	)


def publish_job(timetable, as_of=None):
	"""The job: publish, or record why not. A failure rolls back to the start and leaves the old schedules as they were."""
	frappe.db.savepoint(SAVEPOINT)
	frappe.db.set_value("Timetable", timetable, {"publish_state": "Publishing", "publish_error": None}, update_modified=False)
	try:
		publish_now(timetable, as_of=as_of)
	except Exception as error:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.db.set_value("Timetable", timetable, {"publish_state": "Failed", "publish_error": str(error)[:1000]}, update_modified=False)
	if not frappe.in_test:
		frappe.db.commit()  # nosemgrep: the worker publishes its outcome; tests run in one rolled-back transaction


def preflight(doc):
	"""Everything that would make a publish fail, checked up front. Raises with the reasons."""
	doc.check_hard_constraints()
	missing = sorted({e.faculty for e in doc.entries if not instructor_of(e.faculty)})
	if missing:
		frappe.throw(_("No Instructor record for {0}, so their classes cannot be scheduled.").format(", ".join(missing)), title=_("Cannot Publish"))
	clashes = cross_timetable_clashes(doc)
	if clashes:
		frappe.throw("<br>".join(clashes[:12]), title=_("Clashes with Another Published Timetable"))


def instructor_of(employee):
	return frappe.db.get_value("Instructor", {"employee": employee}, "name")


def cross_timetable_clashes(doc):
	"""Teacher or room used at the same time by another published Timetable of the company and term."""
	others = frappe.get_all(
		"Timetable", {"company": doc.company, "academic_term": doc.academic_term, "status": ["in", PUBLISHED], "name": ["!=", doc.name]}, pluck="name"
	)
	if not others:
		return []
	rows = frappe.get_all(
		"Timetable Entry", {"parent": ["in", others]}, ["parent", "faculty", "room", "day", "from_time", "to_time", "offering"]
	)
	found = []
	for mine in doc.entries:
		for other in rows:
			if other.day != mine.day or not overlaps(mine, other):
				continue
			for what, label in (("faculty", _("Teacher")), ("room", _("Room"))):
				if other[what] == mine.get(what):
					found.append(_("{0} {1} is also booked on {2} {3} in {4} ({5}).").format(label, mine.get(what), mine.day, to_timedelta(mine.from_time), other.parent, other.offering))
	return found


def overlaps(a, b):
	return to_timedelta(a.from_time) < to_timedelta(b.to_time) and to_timedelta(b.from_time) < to_timedelta(a.to_time)


def publish_now(timetable, as_of=None):
	"""Replace the future Course Schedules of `timetable`; returns {"created", "removed", "kept"} counts."""
	frappe.db.get_value("Timetable", timetable, "name", for_update=True)  # one publish at a time
	doc = frappe.get_doc("Timetable", timetable, for_update=True)
	preflight(doc)
	term = frappe.db.get_value("Academic Term", doc.academic_term, ["term_start_date", "term_end_date"], as_dict=True)
	start = max(getdate(as_of or today()), getdate(term.term_start_date))
	kept, removed = remove_future_schedules(doc.name, start)
	created = create_schedules(doc, start, getdate(term.term_end_date), kept)
	frappe.db.set_value(
		"Timetable", doc.name,
		{"status": "Published", "published_on": now_datetime(), "publish_state": None, "publish_error": None}, update_modified=False,
	)  # fmt: skip
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
	instructors = {e.faculty: instructor_of(e.faculty) for e in timetable.entries}
	created = 0
	for row in timetable.entries:
		for date in dates[row.day]:
			if slot_key(row.offering, date, row.from_time) in kept:
				continue
			new_schedule(timetable.name, row, instructors[row.faculty], date)
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
