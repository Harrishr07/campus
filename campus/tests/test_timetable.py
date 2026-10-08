"""P2-T07 (M07-03) integration tests: Slot Template checks, background generation from submitted Course Allocations
(clash-free grid, faculty unavailability, unmet constraints reported, run guards), manual edits validated against the
hard constraints, publish into education Course Schedules, re-publish touching only future schedules and never
marked attendance, and the clash checker report.

Fixture: CSE, sections A and B, four courses each. Per section: Theory 1 (3 lectures + 1 tutorial, hod_cse), Theory 2
(3 lectures, faculty_1), Theory 3 (3 lectures + 1 tutorial, faculty_2), Lab (2 practical hours = one 2-period block,
faculty_3) = 13 periods, 12 classes; 26 periods and 24 classes for the two sections. Template: Monday-Friday, periods
1-3, break, 5-6 (25 teaching slots). Rooms: two classrooms and one lab of 40 seats, 30 students a section.
"""

import calendar
from unittest import mock

import frappe
from frappe.utils import add_days, getdate, to_timedelta

from campus.faculty.report.timetable_clash_checker import timetable_clash_checker as checker
from campus.faculty.timetable import context, generation, publish, rules
from campus.tests import demo
from campus.tests.utils import CampusTestCase

CSE = f"{demo.CSE_DEPARTMENT} - DCE"
ECE = f"{demo.ECE_DEPARTMENT} - DCE"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
SECTIONS = ["A", "B"]
# course key, teacher, lecture, tutorial, practical hours a week
PLAN = [("T1", "hod_cse", 3, 1, 0), ("T2", "faculty_1", 3, 0, 0), ("T3", "faculty_2", 3, 1, 0), ("LAB", "faculty_3", 0, 0, 2)]
PERIODS = [(1, "09:00:00", "09:50:00", 0), (2, "10:00:00", "10:50:00", 0), (3, "11:00:00", "11:50:00", 0),
	(4, "12:00:00", "12:50:00", 1), (5, "13:30:00", "14:20:00", 0), (6, "14:30:00", "15:20:00", 0)]  # fmt: skip
TERM_END = getdate("2026-11-30")


def employee(username):
	return demo.employee_of(username)


class TimetableFixture(CampusTestCase):
	demo_scale = "small"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.make_term()
		cls.make_rooms()
		cls.make_template()
		cls.make_offerings()
		cls.make_allocation()

	@classmethod
	def make_term(cls):
		year = demo.year_name(2026)
		frappe.get_doc(
			{"doctype": "Academic Term", "academic_year": year, "term_name": "TT Test Odd", "term_start_date": "2026-06-01", "term_end_date": "2026-11-30"}
		).insert()
		cls.year = year
		cls.term = frappe.db.get_value("Academic Term", {"academic_year": year, "term_name": "TT Test Odd"})

	@classmethod
	def make_rooms(cls):
		cls.rooms = {
			name: demo.get_or_insert("Room", {"room_name": name}, {"room_number": name[-1], "seating_capacity": "40", "oc_room_type": kind, "oc_company": demo.ENGINEERING})
			for name, kind in (("TT Class 1", "Classroom"), ("TT Class 2", "Classroom"), ("TT Lab 1", "Lab"))
		}

	@classmethod
	def make_template(cls):
		cls.template = frappe.get_doc(
			{
				"doctype": "Timetable Slot Template", "template_name": "TT Test Template", "company": demo.ENGINEERING,
				"lab_block_periods": 2, "max_faculty_periods_per_day": 6,
				"days": [{"day": d} for d in DAYS],
				"periods": [{"period": p, "from_time": a, "to_time": b, "is_break": br, "label": "Break" if br else f"P{p}"} for p, a, b, br in PERIODS],
			}
		).insert().name  # fmt: skip

	@classmethod
	def make_offerings(cls):
		program = demo.get_or_insert("Program", {"program_name": "TT Test CSE"}, {"oc_company": demo.ENGINEERING, "department": CSE})
		cls.offerings = {}
		for key, *_rest in PLAN:
			course = demo.get_or_insert("Course", {"course_name": f"TT Course {key}"}, {"oc_company": demo.ENGINEERING})
			for section in SECTIONS:
				cls.offerings[(key, section)] = frappe.get_doc(
					{
						"doctype": "Student Group", "student_group_name": f"TT {key}-{section}", "group_based_on": "Course",
						"academic_year": cls.year, "academic_term": cls.term, "program": program, "course": course,
						"max_strength": 30, "oc_section": section, "oc_semester": 3,
					}
				).insert().name  # fmt: skip

	@classmethod
	def make_allocation(cls):
		allocation = frappe.get_doc(
			{
				"doctype": "Course Allocation", "academic_term": cls.term, "department": CSE,
				"allocations": [
					{"offering": cls.offerings[(key, s)], "faculty": employee(teacher), "lecture_hours": lec, "tutorial_hours": tut, "practical_hours": pra}
					for key, teacher, lec, tut, pra in PLAN
					for s in SECTIONS
				],
			}
		).insert()  # fmt: skip
		frappe.db.set_value("Course Allocation", allocation.name, "docstatus", 1)  # as if approved: the approval flow is T06's

	def setUp(self):
		super().setUp()
		frappe.db.savepoint("tt_test")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="tt_test")
		super().tearDown()

	def new_timetable(self, **extra):
		return frappe.get_doc(
			{"doctype": "Timetable", "company": demo.ENGINEERING, "academic_term": self.term, "slot_template": self.template, "department": CSE, **extra}
		).insert()

	def generated(self, **extra):
		doc = self.new_timetable(**extra)
		run = frappe.get_doc("Timetable Generation Run", generation.start_generation(doc.name))
		doc.reload()
		return doc, run

	def violations_of(self, doc):
		doc.reload()
		return rules.violations(context.entries_of(doc), context.build_grid(doc))


class TestSlotTemplate(TimetableFixture):
	def new_template(self, **extra):
		values = {
			"doctype": "Timetable Slot Template", "template_name": "TT Bad Template", "company": demo.ENGINEERING,
			"days": [{"day": "Monday"}], "periods": [{"period": 1, "from_time": "09:00:00", "to_time": "09:50:00"}],
		}  # fmt: skip
		return frappe.get_doc({**values, **extra})

	def test_a_valid_template_saves(self):
		self.assertTrue(self.new_template().insert().name)

	def test_period_rules(self):
		slot = lambda p, a, b, **kw: {"period": p, "from_time": a, "to_time": b, **kw}  # noqa: E731
		for periods, text in (
			([slot(1, "09:00:00", "09:50:00"), slot(1, "10:00:00", "10:50:00")], "more than once"),
			([slot(1, "10:00:00", "09:00:00")], "before"),
			([slot(1, "09:00:00", "10:00:00"), slot(2, "09:30:00", "10:30:00")], "overlaps"),
			([slot(2, "09:00:00", "09:50:00"), slot(1, "10:00:00", "10:50:00")], "in time order"),
			([slot(1, "09:00:00", "09:50:00", is_break=1)], "teaching period"),
		):
			with self.assertRaises(frappe.ValidationError, msg=text) as caught:
				self.new_template(periods=periods).insert()
			self.assertIn(text, str(caught.exception))

	def test_days_and_block_rules(self):
		with self.assertRaises(frappe.ValidationError):
			self.new_template(days=[{"day": "Monday"}, {"day": "Monday"}]).insert()
		with self.assertRaises(frappe.ValidationError):
			self.new_template(lab_block_periods=0).insert()


class TestGeneration(TimetableFixture):
	def test_room_fields_exist_on_education_room(self):
		self.assertTrue(frappe.get_meta("Room").has_field("oc_room_type"))
		self.assertTrue(frappe.get_meta("Course Schedule").has_field("oc_timetable"))

	def test_generation_places_every_class_clash_free(self):
		doc, run = self.generated()
		self.assertEqual(run.status, "Completed", run.error)
		self.assertEqual((run.sessions_total, run.sessions_placed), (24, 24))
		self.assertEqual(len(doc.entries), 26)
		self.assertEqual(self.violations_of(doc), [])
		self.assertFalse(run.unmet)
		self.assertTrue(run.started_at and run.finished_at)

	def test_labs_are_two_consecutive_periods_in_the_lab(self):
		doc, _run = self.generated()
		for section in SECTIONS:
			lab = sorted((e.day, e.period, e.room) for e in doc.entries if e.offering == self.offerings[("LAB", section)])
			self.assertEqual(len(lab), 2)
			self.assertEqual((lab[0][0], lab[0][2]), (lab[1][0], self.rooms["TT Lab 1"]))
			self.assertEqual(lab[1][1], lab[0][1] + 1)
		self.assertFalse([e for e in doc.entries if e.kind != "Practical" and e.room == self.rooms["TT Lab 1"]])

	def test_lectures_of_a_course_fall_on_different_days_and_times_come_from_the_template(self):
		doc, _run = self.generated()
		for key in ("T1", "T2", "T3"):
			days = [e.day for e in doc.entries if e.offering == self.offerings[(key, "A")] and e.kind == "Lecture"]
			self.assertEqual(len(days), len(set(days)), key)
		slot = {p: (a, b) for p, a, b, _br in PERIODS}
		for e in doc.entries:
			self.assertEqual((to_timedelta(e.from_time), to_timedelta(e.to_time)), tuple(map(to_timedelta, slot[e.period])), e.period)
		self.assertTrue(all(e.section for e in doc.entries))

	def test_faculty_unavailability_is_respected(self):
		hod = employee("hod_cse")
		doc, run = self.generated(unavailability=[{"faculty": hod, "day": "Monday", "period": 0}, {"faculty": hod, "day": "Tuesday", "period": 1}])
		self.assertEqual(run.status, "Completed", run.error)
		mine = [(e.day, e.period) for e in doc.entries if e.faculty == hod]
		self.assertEqual(len(mine), 8)
		self.assertFalse([m for m in mine if m[0] == "Monday" or m == ("Tuesday", 1)])

	def test_unsatisfiable_constraints_are_reported_not_hidden(self):
		lab_teacher = employee("faculty_3")
		doc, run = self.generated(unavailability=[{"faculty": lab_teacher, "day": d, "period": 0} for d in DAYS])
		self.assertEqual(run.status, "Completed with unmet constraints")
		self.assertEqual((run.sessions_total, run.sessions_placed), (24, 22))
		self.assertEqual(run.unmet.count(lab_teacher), 2)  # one line per lab block, both name the teacher and say why
		self.assertIn("unavailable", run.unmet)
		self.assertFalse([e for e in doc.entries if e.faculty == lab_teacher])
		self.assertEqual(self.violations_of(doc), [])

	def test_a_class_too_big_for_any_lab_is_reported(self):
		for section in SECTIONS:
			frappe.db.set_value("Student Group", self.offerings[("LAB", section)], "max_strength", 5000)
		_doc, run = self.generated()
		self.assertEqual(run.status, "Completed with unmet constraints")
		self.assertEqual(run.sessions_placed, 22)
		self.assertIn("5000", run.unmet)

	def test_regenerating_replaces_the_grid(self):
		doc, _run = self.generated()
		generation.start_generation(doc.name)
		doc.reload()
		self.assertEqual(len(doc.entries), 26)
		self.assertEqual(frappe.db.count("Timetable Generation Run", {"timetable": doc.name, "status": "Completed"}), 2)

	def test_only_one_live_run_per_timetable(self):
		doc = self.new_timetable()
		frappe.get_doc({"doctype": "Timetable Generation Run", "timetable": doc.name, "status": "Running"}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			generation.start_generation(doc.name)

	def test_a_run_without_course_allocations_fails_with_the_reason(self):
		doc = self.new_timetable(department=ECE)
		run = frappe.get_doc("Timetable Generation Run", generation.start_generation(doc.name))
		self.assertEqual(run.status, "Failed")
		self.assertIn("Course Allocation", run.error)

	def test_generation_needs_write_permission_on_the_timetable(self):
		doc = self.new_timetable()
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			generation.start_generation(doc.name)


class TestManualEdits(TimetableFixture):
	def setUp(self):
		super().setUp()
		self.doc, _run = self.generated()

	def row(self, key, section, kind=None):
		return next(e for e in self.doc.entries if e.offering == self.offerings[(key, section)] and (kind is None or e.kind == kind))

	def occupied(self, **match):
		return {(e.day, e.period) for e in self.doc.entries if all(getattr(e, k) == v for k, v in match.items())}

	def free_slot_for(self, row):
		busy = self.occupied(section=row.section) | self.occupied(faculty=row.faculty)
		return next((d, p) for d in DAYS for p in (1, 2, 3, 5, 6) if (d, p) not in busy)

	def test_moving_a_class_to_a_free_slot_saves(self):
		row = self.row("T2", "A", "Lecture")
		row.day, row.period = self.free_slot_for(row)
		self.doc.save()
		self.assertEqual(self.violations_of(self.doc), [])

	def test_a_section_clash_is_refused(self):
		a, b = self.row("T2", "A", "Lecture"), self.row("T3", "A", "Lecture")
		a.day, a.period = b.day, b.period
		with self.assertRaises(frappe.ValidationError) as caught:
			self.doc.save()
		self.assertIn("Section", str(caught.exception))

	def test_a_faculty_clash_is_refused(self):
		a, b = self.row("T1", "A", "Lecture"), self.row("T1", "B", "Lecture")
		a.day, a.period = b.day, b.period  # hod_cse in two sections at once
		with self.assertRaises(frappe.ValidationError) as caught:
			self.doc.save()
		self.assertIn(a.faculty, str(caught.exception))

	def test_breaking_up_a_lab_block_is_refused(self):
		lab = [e for e in self.doc.entries if e.offering == self.offerings[("LAB", "A")]]
		lab[1].period = 1 if lab[0].period != 1 else 6
		lab[1].day = lab[0].day
		if abs(lab[1].period - lab[0].period) == 1:
			lab[1].period = 6 if lab[0].period != 6 else 1
		with self.assertRaises(frappe.ValidationError) as caught:
			self.doc.save()
		self.assertIn("consecutive", str(caught.exception))

	def test_practical_in_a_classroom_is_refused(self):
		for e in self.doc.entries:
			if e.offering == self.offerings[("LAB", "A")]:
				e.room = self.rooms["TT Class 1"]
		with self.assertRaises(frappe.ValidationError):
			self.doc.save()

	def test_a_break_period_is_refused(self):
		self.row("T2", "A", "Lecture").period = 4
		with self.assertRaises(frappe.ValidationError):
			self.doc.save()

	def test_a_new_unavailability_rejects_the_existing_class(self):
		row = self.row("T2", "A", "Lecture")
		self.doc.append("unavailability", {"faculty": row.faculty, "day": row.day, "period": row.period})
		with self.assertRaises(frappe.ValidationError) as caught:
			self.doc.save()
		self.assertIn("unavailable", str(caught.exception))

	def test_the_section_and_times_follow_an_edit(self):
		row = self.row("T2", "A", "Lecture")
		row.day, row.period = self.free_slot_for(row)
		self.doc.save()
		self.assertEqual(to_timedelta(self.doc.entries[row.idx - 1].from_time), to_timedelta(dict((p, a) for p, a, *_r in PERIODS)[row.period]))


def weekday_count(day, start):
	number = list(calendar.day_name).index(day)
	return sum(1 for n in range((TERM_END - getdate(start)).days + 1) if add_days(getdate(start), n).weekday() == number)


class TestPublish(TimetableFixture):
	FIRST, SECOND = "2026-11-16", "2026-11-24"  # Mondays/Tuesdays of the last weeks of the term

	def schedules(self, doc, **extra):
		return frappe.get_all(
			"Course Schedule", {"oc_timetable": doc.name, **extra},
			["name", "student_group", "instructor", "room", "schedule_date", "from_time", "to_time"], order_by="schedule_date, from_time, student_group",
		)  # fmt: skip

	def published(self, as_of=None):
		doc, _run = self.generated()
		publish.publish_now(doc.name, as_of=as_of or self.FIRST)
		doc.reload()
		return doc

	def test_publish_creates_course_schedules_for_the_term(self):
		doc = self.published()
		expected = sum(weekday_count(e.day, self.FIRST) for e in doc.entries)
		schedules = self.schedules(doc)
		self.assertEqual(len(schedules), expected)
		self.assertEqual(doc.status, "Published")
		self.assertTrue(doc.published_on)
		entry = doc.entries[0]
		mine = [
			s for s in schedules
			if s.student_group == entry.offering and s.from_time == to_timedelta(entry.from_time) and calendar.day_name[getdate(s.schedule_date).weekday()] == entry.day
		]
		self.assertEqual(len(mine), weekday_count(entry.day, self.FIRST))
		self.assertEqual(mine[0].room, entry.room)
		self.assertEqual(mine[0].instructor, frappe.db.get_value("Instructor", {"employee": entry.faculty}))
		self.assertEqual(calendar.day_name[getdate(mine[0].schedule_date).weekday()], entry.day)
		self.assertTrue(all(getdate(s.schedule_date) >= getdate(self.FIRST) for s in schedules))

	def test_a_grid_with_clashes_is_not_published(self):
		doc, _run = self.generated()
		a, b = doc.entries[0], doc.entries[1]
		frappe.db.set_value("Timetable Entry", a.name, {"day": b.day, "period": b.period, "section": b.section, "faculty": b.faculty})  # past validate
		with self.assertRaises(frappe.ValidationError):
			publish.publish_now(doc.name, as_of=self.FIRST)
		self.assertEqual(frappe.db.count("Course Schedule", {"oc_timetable": doc.name}), 0)
		self.assertEqual(frappe.db.get_value("Timetable", doc.name, "status"), "Draft")

	def mark(self, schedule, status="Present"):
		student = frappe.get_all("Student", pluck="name", limit=1)[0]
		row = frappe.get_doc(
			{"doctype": "Student Attendance", "student": student, "student_group": schedule.student_group, "course_schedule": schedule.name, "date": schedule.schedule_date, "status": status}
		)
		row.flags.ignore_validate = True  # education's holiday-list check is not under test
		row.insert(ignore_permissions=True)
		row.submit()
		return row.name

	def test_republish_replaces_only_future_schedules_and_keeps_marked_attendance(self):
		doc = self.published()
		before = self.schedules(doc)
		past = [s for s in before if getdate(s.schedule_date) < getdate(self.SECOND)]
		future = [s for s in before if getdate(s.schedule_date) >= getdate(self.SECOND)]
		self.assertTrue(past and future)
		moved = next(e for e in doc.entries if e.kind == "Lecture")
		marked_moved = next(s for s in future if s.student_group == moved.offering and calendar.day_name[getdate(s.schedule_date).weekday()] == moved.day)
		unchanged = next(e for e in doc.entries if e.kind == "Lecture" and e.name != moved.name)
		marked_same = next(s for s in future if s.student_group == unchanged.offering and calendar.day_name[getdate(s.schedule_date).weekday()] == unchanged.day)
		attendance = [self.mark(marked_moved), self.mark(marked_same), self.mark(past[0])]
		busy = {(e.day, e.period) for e in doc.entries if e.section == moved.section or e.faculty == moved.faculty}
		moved.day, moved.period = next((d, p) for d in DAYS for p in (1, 2, 3, 5, 6) if (d, p) not in busy)
		doc.save()
		result = publish.publish_now(doc.name, as_of=self.SECOND)
		after = self.schedules(doc)
		names = {s.name for s in after}
		self.assertTrue({s.name for s in past} <= names, "past schedules are untouched")
		self.assertTrue({marked_moved.name, marked_same.name} <= names, "schedules with marked attendance are kept")
		self.assertEqual(frappe.db.count("Student Attendance", {"name": ["in", attendance]}), 3)
		self.assertEqual(result["removed"], len(future) - 2)  # every future schedule but the two with attendance (names can be reused, so count)
		self.assertEqual(result["kept"], 2)
		new_time = to_timedelta(moved.from_time)
		at_new_slot = [
			x for x in after
			if x.student_group == moved.offering and x.from_time == new_time and getdate(x.schedule_date) >= getdate(self.SECOND)
			and calendar.day_name[getdate(x.schedule_date).weekday()] == moved.day
		]  # fmt: skip
		self.assertEqual(len(at_new_slot), weekday_count(moved.day, self.SECOND))  # the moved class exists at its new slot
		same_slot = [s for s in after if (s.student_group, s.schedule_date, s.from_time) == (marked_same.student_group, marked_same.schedule_date, marked_same.from_time)]
		self.assertEqual(len(same_slot), 1, "a kept schedule is not created a second time")

	def test_republish_leaves_schedules_of_other_sources_alone(self):
		doc = self.published()
		entry = doc.entries[0]
		other = frappe.get_doc(
			{
				"doctype": "Course Schedule", "student_group": entry.offering, "course": frappe.db.get_value("Student Group", entry.offering, "course"),
				"instructor": frappe.db.get_value("Instructor", {"employee": employee("faculty_3")}), "room": self.rooms["TT Class 2"],
				"schedule_date": "2026-11-27", "from_time": "17:00:00", "to_time": "17:50:00",
			}
		).insert(ignore_permissions=True)  # fmt: skip
		publish.publish_now(doc.name, as_of=self.SECOND)
		self.assertTrue(frappe.db.exists("Course Schedule", other.name))

	def test_publish_runs_through_the_background_job_entry_point(self):
		doc, _run = self.generated()
		publish.publish_timetable(doc.name)  # in tests the job runs inline
		self.assertEqual(frappe.db.get_value("Timetable", doc.name, "status"), "Published")
		self.assertTrue(frappe.db.count("Course Schedule", {"oc_timetable": doc.name}))


class TestClashChecker(TimetableFixture):
	def run_report(self, doc):
		return checker.execute({"company": demo.ENGINEERING, "timetable": doc.name})

	def test_a_generated_timetable_has_no_clashes(self):
		doc, _run = self.generated()
		columns, rows, *_rest = self.run_report(doc)
		self.assertTrue(columns)
		self.assertEqual(rows, [])

	def test_clashes_are_listed_with_slot_and_parties(self):
		doc, _run = self.generated()
		a, b = doc.entries[0], next(e for e in doc.entries if e.faculty != doc.entries[0].faculty and e.section != doc.entries[0].section)
		frappe.db.set_value("Timetable Entry", b.name, {"day": a.day, "period": a.period, "room": a.room})  # past validate: same room, same slot
		_columns, rows, *_rest = self.run_report(doc)
		self.assertIn(rules.ROOM_CLASH, {r["rule"] for r in rows})
		clash = next(r for r in rows if r["rule"] == rules.ROOM_CLASH)
		self.assertEqual((clash["day"], clash["period"], clash["subject"]), (a.day, a.period, a.room))

	def test_a_user_limited_to_another_company_sees_nothing(self):
		doc, _run = self.generated()
		frappe.db.set_value("Timetable Entry", doc.entries[1].name, {"day": doc.entries[0].day, "period": doc.entries[0].period, "room": doc.entries[0].room})
		with mock.patch.object(checker, "permitted_companies", return_value=["Some Other College"]):
			_columns, rows, *_rest = self.run_report(doc)
		self.assertEqual(rows, [])
