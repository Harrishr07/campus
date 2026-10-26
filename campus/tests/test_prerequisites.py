"""P2-T26 integration tests (M03-04, M03-07, M05-03): prerequisites from published results and Honours / Minor
eligibility in Course Registration.

A prerequisite is met only by a Pass in the latest, ratified Student Result of a released Exam Session (Published,
publish_at passed). A row whose prerequisite has no such evidence is held with the reason (the registration saves
and goes to review) and a held row blocks final approval; it is never auto-passed. Honours / Minor need the
Registration Rule's minimum CGPA over the curriculum's courses up to its semester, and Honours no outstanding arrear.

Fixture (on the P1-T13 registration world): REG C needs REG E; REG D needs REG E and REG S4. Results of an earlier
released session and an unreleased one, per student (index into STUDENTS):
0 REG E Pass (9), REG S4 Pass (8), REG B Pass (5): every prerequisite met; CGPA up to semester 3 is 9
1 REG E Fail: an arrear, CGPA 0
2 no results
3 REG E Pass only in the unreleased session
4 REG E Fail, ratified; a Pass in a version still pending ratification
5 REG E Pass (8), REG S4 Fail: CGPA up to semester 3 is 8 with an arrear
"""

import frappe
from frappe.utils import add_days, now_datetime

from campus.tests.test_registration import COLLEGE, PROGRAM, RegistrationTestCase, make_term

HELD = r"prerequisite"


def make_session(term, released=True):
	session = frappe.get_doc(
		{"doctype": "Exam Session", "company": COLLEGE, "academic_term": term, "status": "Marks Entry"}
	).insert()
	publish_at = add_days(now_datetime(), -1 if released else 3)
	frappe.db.set_value("Exam Session", session.name, {"status": "Published", "publish_at": publish_at})
	return session.name


def make_result(student, session, rows, version=1, is_latest=1, pending=0):
	"""A Student Result of `rows` (course, grade point, result, credits); the name is free so versions can coexist."""
	doc = frappe.get_doc(
		{
			"doctype": "Student Result", "student": student, "exam_session": session, "company": COLLEGE,
			"academic_term": frappe.db.get_value("Exam Session", session, "academic_term"), "program": PROGRAM,
			"regulation": frappe.db.get_value("Student", student, "oc_regulation"), "version": version,
			"is_latest": is_latest, "pending_ratification": pending,
			"result": "Pass" if all(r[2] == "Pass" for r in rows) else "Reappear",
			"courses": [
				{"course": c, "grade_point": gp, "result": result, "credits": credits, "in_gpa": 1, "kind": "Current"}
				for c, gp, result, credits in rows
			],
		}
	)  # fmt: skip
	doc.name = f"SR-PRQ-{frappe.generate_hash(length=8)}"
	doc.db_insert()
	for row in doc.courses:
		row.parent, row.parenttype, row.parentfield = doc.name, "Student Result", "courses"
		row.db_insert()
	return doc.name


class PrerequisiteTestCase(RegistrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for course, prerequisites in (("REG C", "REG E"), ("REG D", "REG E, REG S4")):
			frappe.db.set_value(
				"Curriculum Course",
				{"parent": cls.curriculum.name, "course": course},
				"prerequisites",
				prerequisites,
			)
		frappe.db.set_value(
			"Registration Rule", cls.rule.name,
			{"honours_min_cgpa": 7.5, "honours_cgpa_upto_semester": 3, "honours_no_arrears": 1, "honours_clause": "8.2"},
		)  # fmt: skip
		cls.released = make_session(make_term("Reg Prior", "2022-12-01", "2022-12-15"))
		cls.unreleased = make_session(make_term("Reg Prior Late", "2022-12-16", "2022-12-31"), released=False)
		s = [student.name for student in cls.students]
		make_result(
			s[0], cls.released, [("REG E", 9, "Pass", 4), ("REG S4", 8, "Pass", 3), ("REG B", 5, "Pass", 18)]
		)
		make_result(s[1], cls.released, [("REG E", 0, "Fail", 4)])
		make_result(s[3], cls.unreleased, [("REG E", 9, "Pass", 4)])
		make_result(s[4], cls.released, [("REG E", 0, "Fail", 4)])
		make_result(s[4], cls.released, [("REG E", 9, "Pass", 4)], version=2, is_latest=0, pending=1)
		make_result(s[5], cls.released, [("REG E", 8, "Pass", 4), ("REG S4", 0, "Fail", 3)])

	def hold(self, registration, course):
		return next(row.hold_reason for row in registration.items if row.course == course)


class TestPrerequisites(PrerequisiteTestCase):
	def test_a_prerequisite_passed_in_a_released_result_is_met(self):
		registration = self.regular("REG C", "REG D", student=0)
		self.assertFalse(self.hold(registration, "REG C"))
		self.assertFalse(self.hold(registration, "REG D"))
		registration.submit()
		self.assertEqual(self.enrollments(0, "REG C"), 1)

	def test_a_failed_prerequisite_holds_the_row_with_the_reason(self):
		registration = self.regular("REG C", student=1)
		self.assertEqual(registration.docstatus, 0)  # saved: sent to review, not refused outright
		self.assertRegex(self.hold(registration, "REG C"), r"REG E.*published result")

	def test_a_held_row_blocks_final_approval(self):
		registration = self.regular("REG C", student=1)
		with self.assertRaisesRegex(frappe.ValidationError, r"REG C.*held"):
			registration.submit()
		self.assertEqual(self.enrollments(1, "REG C"), 0)

	def test_no_result_holds_the_row(self):
		self.assertRegex(self.hold(self.regular("REG C", student=2), "REG C"), "REG E")

	def test_only_the_missing_prerequisites_are_named(self):
		reason = self.hold(self.regular("REG D", student=5), "REG D")  # REG E passed, REG S4 failed
		self.assertIn("REG S4", reason)
		self.assertNotIn("REG E", reason)

	def test_a_pass_in_an_unreleased_session_counts_once_released(self):
		registration = self.regular("REG C", student=3)
		self.assertRegex(self.hold(registration, "REG C"), "REG E")
		publish_at = frappe.db.get_value("Exam Session", self.unreleased, "publish_at")
		self.addCleanup(frappe.db.set_value, "Exam Session", self.unreleased, "publish_at", publish_at)
		frappe.db.set_value("Exam Session", self.unreleased, "publish_at", add_days(now_datetime(), -1))
		registration.reload()
		registration.submit()  # re-evaluated on submit: the evidence is now published
		self.assertFalse(self.hold(registration, "REG C"))
		self.assertEqual(self.enrollments(3, "REG C"), 1)

	def test_a_pass_pending_ratification_does_not_count(self):
		self.assertRegex(self.hold(self.regular("REG C", student=4), "REG C"), "REG E")

	def test_a_dropped_row_is_not_checked(self):
		self.regular("REG C", student=0).submit()
		drop = self.registration([("REG C", "Dropped")], student=0)
		self.assertFalse(self.hold(drop, "REG C"))

	def test_the_examinations_api_reads_published_ratified_passes(self):
		from campus.examinations.api import has_passed

		self.assertTrue(has_passed(self.students[0].name, "REG E"))
		for student in (1, 2, 3, 4):
			self.assertFalse(has_passed(self.students[student].name, "REG E"), student)


class TestHonoursEligibility(PrerequisiteTestCase):
	def test_honours_is_refused_for_a_student_with_an_arrear(self):
		self.assert_rejected(
			[("REG AD1", "Honours")], r"R2022 cl\. 8\.2: .*no outstanding arrear.*REG S4", student=5
		)

	def test_minor_is_allowed_with_an_arrear_when_the_cgpa_is_met(self):
		self.registration([("REG AD1", "Minor")], student=5)

	def test_honours_with_the_cgpa_up_to_semester_three_and_no_arrear_is_allowed(self):
		# the overall CGPA is (9x4 + 8x3 + 5x18) / 25 = 6, but semesters 1-3 hold only REG E at 9
		self.registration([("REG AD1", "Honours")], student=0)

	def test_a_cgpa_below_the_minimum_refuses_minor(self):
		self.assert_rejected([("REG AD1", "Minor")], r"at least 7\.5 up to semester 3", student=2)

	def test_regular_rows_are_not_checked(self):
		self.registration([("REG A", "Regular")], student=1)
