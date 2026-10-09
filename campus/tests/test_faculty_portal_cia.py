"""P2-T11 (M06-08) API permission tests for CIA entry on the faculty portal: the teacher's own Mark Sheet Entry only,
question-wise marks under the T13 lock, a schedule without questions read-only, the CIA column without a schedule,
a published session final. Fixture: the T13 CIA fixture."""

import frappe

from campus.faculty import portal_cia
from campus.tests.test_cia import THEORY_PATTERN, CIAFixture
from campus.tests.test_results import FACULTY, OTHER_FACULTY, STUDENT_22_USER


class TestCIAEntry(CIAFixture):
	def setUp(self):
		super().setUp()
		frappe.db.savepoint("faculty_portal_cia")
		self.offering = self.offerings22["EXM TH"]  # FACULTY instructs it; OTHER_FACULTY nothing
		self.schedule(self.offering, THEORY_PATTERN)
		self.sheet_name = self.sheet(self.offering).name

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="faculty_portal_cia")
		super().tearDown()

	def as_user(self, user, fn, *args, **kwargs):
		frappe.set_user(user)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def payload(self, value):
		return [{"student": self.s22.name, "component": c, "question": q, "marks": value, "absent": 0} for c, q, *_tags in THEORY_PATTERN]

	def test_the_teacher_enters_question_marks_and_cia_consolidates(self):
		self.as_user(FACULTY, portal_cia.save_cia_marks, self.sheet_name, frappe.as_json(self.payload(20)))
		sheet = self.sheet(self.offering)
		self.assertEqual({r.marks for r in sheet.cia_marks if r.student == self.s22.name}, {20})
		view = self.as_user(FACULTY, portal_cia.cia_sheet, self.sheet_name)
		self.assertEqual((view["lock_state"], view["editable"]), ("Open", True))
		row = next(s for s in view["students"] if s["student"] == self.s22.name)
		self.assertEqual(row["cia"], next(r.cia for r in sheet.marks if r.student == self.s22.name))
		self.assertGreater(row["cia"], 0)

	def test_another_teacher_or_a_student_is_refused(self):
		for user in (OTHER_FACULTY, STUDENT_22_USER, "Guest"):
			for call, args in ((portal_cia.save_cia_marks, (self.sheet_name, self.payload(5))), (portal_cia.cia_sheet, (self.sheet_name,))):
				with self.assertRaises(frappe.PermissionError, msg=user):
					self.as_user(user, call, *args)
		self.assertFalse(any(r.marks for r in self.sheet(self.offering).cia_marks))

	def test_a_sheet_of_an_offering_the_teacher_does_not_instruct_is_refused(self):
		other = self.sheet(self.offerings22["EXM LB"]).name
		self.assertNotIn(other, [s["name"] for s in self.as_user(FACULTY, portal_cia.my_mark_sheets)])
		with self.assertRaises(frappe.PermissionError):
			self.as_user(FACULTY, portal_cia.save_cia_marks, other, [])

	def test_the_lock_is_respected(self):
		self.as_user(FACULTY, portal_cia.save_cia_marks, self.sheet_name, self.payload(10))
		self.pass_deadline(frappe.get_doc("CIA Schedule", {"course_offering": self.offering}))
		self.assertFalse(self.as_user(FACULTY, portal_cia.cia_sheet, self.sheet_name)["editable"])
		with self.assertRaises(frappe.ValidationError) as caught:
			self.as_user(FACULTY, portal_cia.save_cia_marks, self.sheet_name, self.payload(12))
		self.assertIn("locked", str(caught.exception).lower())
		self.assertEqual({r.marks for r in self.sheet(self.offering).cia_marks if r.student == self.s22.name}, {10})

	def test_a_question_mark_can_be_cleared(self):
		self.as_user(FACULTY, portal_cia.save_cia_marks, self.sheet_name, self.payload(20))
		cleared = [{**row, "marks": None} for row in self.payload(0)[:1]]
		self.as_user(FACULTY, portal_cia.save_cia_marks, self.sheet_name, cleared)
		rows = {(r.component, r.question): r.marks for r in self.sheet(self.offering).cia_marks if r.student == self.s22.name}
		first = tuple(THEORY_PATTERN[0][:2])
		self.assertEqual(rows[first], 0)
		self.assertEqual({v for k, v in rows.items() if k != first}, {20})

	def test_a_schedule_without_questions_shows_the_consolidated_cia_read_only(self):
		schedule = frappe.db.get_value("CIA Schedule", {"course_offering": self.offering})
		frappe.db.delete("CIA Schedule Question", {"parent": schedule})
		view = self.as_user(FACULTY, portal_cia.cia_sheet, self.sheet_name)
		self.assertEqual((view["entry"], view["questions"]), ("consolidated", []))
		with self.assertRaises(frappe.ValidationError):
			self.as_user(FACULTY, portal_cia.save_cia_marks, self.sheet_name, [{"student": self.s22.name, "cia": 30}])

	def test_without_a_schedule_the_cia_column_is_entered_and_a_blank_keeps_it(self):
		schedule = frappe.db.get_value("CIA Schedule", {"course_offering": self.offering})
		frappe.db.delete("CIA Schedule Question", {"parent": schedule})
		frappe.db.delete("CIA Schedule Component", {"parent": schedule})
		frappe.db.delete("CIA Schedule", {"name": schedule})
		self.assertEqual(self.as_user(FACULTY, portal_cia.cia_sheet, self.sheet_name)["entry"], "column")
		self.as_user(FACULTY, portal_cia.save_cia_marks, self.sheet_name, [{"student": self.s22.name, "cia": 30}])
		self.as_user(FACULTY, portal_cia.save_cia_marks, self.sheet_name, [{"student": self.s22.name, "cia": ""}])
		self.assertEqual(next(r.cia for r in self.sheet(self.offering).marks if r.student == self.s22.name), 30)

	def test_a_published_session_is_final_not_locked(self):
		frappe.db.set_value("Exam Session", self.session.name, "status", "Published")
		view = self.as_user(FACULTY, portal_cia.cia_sheet, self.sheet_name)
		self.assertEqual((view["editable"], view["published"]), (False, True))

	def test_unknown_rows_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.as_user(FACULTY, portal_cia.save_cia_marks, self.sheet_name, [{"student": self.s22.name, "component": "Nope", "question": "Q9", "marks": 1}])

	def test_the_save_accepts_post_only(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[portal_cia.save_cia_marks], ["POST"])

	def test_my_mark_sheets_lists_own_offerings(self):
		self.assertEqual([s["name"] for s in self.as_user(FACULTY, portal_cia.my_mark_sheets)], [self.sheet_name])
		with self.assertRaises(frappe.PermissionError):
			self.as_user(STUDENT_22_USER, portal_cia.my_mark_sheets)
