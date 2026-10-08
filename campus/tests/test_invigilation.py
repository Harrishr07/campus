"""M06-02 integration tests: the Invigilation Roster of an Exam Session (AC2: balanced within one per faculty per
session type; nobody in a hall writing their own course; nobody on approved leave) and the invigilation order print.

Uses the seating fixture: five sittings (two FN with halls A and B, three AN with hall A) = 4 FN and 3 AN duties.
faculty_1 teaches SEAT C1 (written on day 1 FN); faculty_2 is on approved leave on day 2.
"""

from collections import Counter
from unittest.mock import patch

import frappe

from campus.examinations import api, invigilation, seating
from campus.tests import demo
from campus.tests.test_exam_seating import COE_USER, DAY1, DAY2, DAY3, SeatingFixture, course, make_plan

TEACHERS = ["hod_cse", "faculty_1", "faculty_2", "faculty_3"]
SITTINGS = [(DAY1, "FN"), (DAY1, "AN"), (DAY2, "FN"), (DAY2, "AN"), (DAY3, "AN")]


class RosterFixture(SeatingFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.teachers = {t: demo.employee_of(t) for t in TEACHERS}
		frappe.get_doc(
			{
				"doctype": "Student Group", "student_group_name": "SEAT C1 offering", "group_based_on": "Course",
				"academic_year": demo.year_name(2026), "academic_term": cls.term, "program": "B.E. CSE", "course": course("C1"),
				"oc_company": demo.ENGINEERING, "instructors": [{"instructor": "faculty_1"}],
			}
		).insert()  # fmt: skip
		frappe.get_doc(
			{
				"doctype": "Leave Application", "name": "SEAT-TEST-LEAVE", "employee": cls.teachers["faculty_2"],
				"from_date": DAY2, "to_date": DAY2, "status": "Approved", "docstatus": 1, "company": demo.ENGINEERING,
				"posting_date": DAY1,
			}
		).db_insert()  # only the approved-leave facts the faculty check reads; HRMS leave rules are not under test
		for exam_date, slot in SITTINGS:
			halls = cls.rooms.values() if slot == "FN" else [cls.rooms["Seat Hall A"]]
			seating.generate(make_plan(cls.session, exam_date, slot, list(halls)).name)

	def roster(self, faculty=None, per_hall=1):
		doc = frappe.get_doc(
			{
				"doctype": "Invigilation Roster", "exam_session": self.session, "invigilators_per_hall": per_hall,
				"faculty": [{"employee": self.teachers[t]} for t in (TEACHERS if faculty is None else faculty)],
			}
		).insert()  # fmt: skip
		invigilation.generate(doc.name)
		return doc.reload()


class TestRoster(RosterFixture):
	def test_duties_are_balanced_within_one_per_session_type(self):  # AC2
		roster = self.roster()
		self.assertEqual(len(roster.duties), 7)
		for slot in ("FN", "AN"):
			counts = Counter(d.employee for d in roster.duties if d.slot == slot)
			loads = [counts[e] for e in self.teachers.values()]
			self.assertLessEqual(max(loads) - min(loads), 1, (slot, loads))

	def test_the_roster_stores_its_largest_duty_gap_and_warns_above_one(self):
		roster = self.roster()
		self.assertLessEqual(roster.duty_spread, 1)
		frappe.clear_messages()
		with patch.object(invigilation.invigilation_rules, "spread", lambda duties, faculty: {"FN": 2, "AN": 0}):
			invigilation.generate(roster.name)
		self.assertEqual(roster.reload().duty_spread, 2)
		self.assertIn("differ by 2", str(frappe.message_log))

	def test_nobody_invigilates_a_hall_writing_their_own_course(self):
		roster = self.roster()
		c1_halls = set(
			frappe.get_all("Seating Plan Seat", {"parenttype": "Seating Plan", "course": course("C1")}, pluck="room")
		)
		own = [d for d in roster.duties if d.employee == self.teachers["faculty_1"] and str(d.exam_date) == DAY1 and d.slot == "FN"]
		self.assertFalse([d for d in own if d.room in c1_halls])

	def test_nobody_on_approved_leave_that_day_is_used(self):
		roster = self.roster()
		self.assertFalse([d for d in roster.duties if d.employee == self.teachers["faculty_2"] and str(d.exam_date) == DAY2])
		self.assertTrue([d for d in roster.duties if d.employee == self.teachers["faculty_2"]])

	def test_an_empty_pool_takes_the_company_teachers(self):
		roster = self.roster(faculty=[])
		self.assertTrue(set(self.teachers.values()) <= {row.employee for row in roster.faculty})
		self.assertTrue(all(d.employee_name for d in roster.duties))

	def test_a_hall_nobody_may_take_refuses_the_roster(self):
		with self.assertRaisesRegex(frappe.ValidationError, "No free invigilator"):
			self.roster(faculty=["hod_cse", "faculty_3"], per_hall=2)  # day 1 FN needs 4 places

	def test_duties_are_server_owned(self):
		roster = self.roster()
		roster.duties[0].employee = self.teachers["faculty_3"] if roster.duties[0].employee != self.teachers["faculty_3"] else self.teachers["hod_cse"]
		with self.assertRaisesRegex(frappe.ValidationError, "Generate Roster"):
			roster.save()

	def test_only_the_coe_generates_and_only_by_post(self):
		doc = frappe.get_doc({"doctype": "Invigilation Roster", "exam_session": self.session}).insert()
		frappe.set_user(demo.email("faculty_1"))
		with self.assertRaises(frappe.PermissionError):
			api.generate_invigilation(doc.name)
		frappe.set_user(COE_USER)
		self.assertGreater(api.generate_invigilation(doc.name), 0)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[api.generate_invigilation], ["POST"])

	def test_the_invigilation_order_prints_escaped(self):
		roster = self.roster()
		frappe.db.set_value("Invigilation Duty", roster.duties[0].name, "employee_name", "<b>x</b><script>alert(2)</script>")
		html = frappe.get_print("Invigilation Roster", roster.name, "Invigilation Order")
		self.assertIn(roster.duties[1].employee_name, html)
		self.assertNotIn("<script>alert(2)</script>", html)
		self.assertIn("&lt;script&gt;", html)
