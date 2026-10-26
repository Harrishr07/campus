"""R-05 tests (M03-08): the backfill that binds old Course Registrations to the enrollment they were made for."""

import frappe
from frappe.tests import UnitTestCase

from campus.patches import bind_course_registrations_to_enrollment as patch
from campus.tests.test_registration import PROGRAM, RegistrationTestCase
from campus.tests.test_regulation import enroll, make_year


class TestChooseEnrollment(UnitTestCase):
	def test_the_only_candidate_is_chosen(self):
		self.assertEqual(patch.choose_enrollment(["PE1"], set()), "PE1")

	def test_several_candidates_are_narrowed_by_the_course_enrollments_in_use(self):
		self.assertEqual(patch.choose_enrollment(["PE1", "PE2"], {"PE2", "PE9"}), "PE2")

	def test_several_candidates_all_in_use_is_ambiguous(self):
		self.assertIsNone(patch.choose_enrollment(["PE1", "PE2"], {"PE1", "PE2"}))

	def test_several_candidates_none_in_use_is_ambiguous(self):
		self.assertIsNone(patch.choose_enrollment(["PE1", "PE2"], set()))

	def test_no_candidate_is_unresolved(self):
		self.assertIsNone(patch.choose_enrollment([], {"PE1"}))


class TestBindRegistrations(RegistrationTestCase):
	def legacy_registration(self, student, **timestamps):
		"""A registration of the 2022 enrollment, made before the student re-enrolled in 2023, with no binding."""
		first = frappe.db.get_value("Program Enrollment", {"student": self.students[student].name}, "name")
		make_year("2023")
		second = enroll(self.students[student], PROGRAM, "2023").name
		doc = self.regular("REG C", student=student)
		stamps = {
			first: "2022-06-02 10:00:00",
			second: "2023-06-02 10:00:00",
			doc.name: "2022-06-10 12:00:00",
			**timestamps,
		}
		for name, stamp in stamps.items():
			doctype = "Course Registration" if name == doc.name else "Program Enrollment"
			frappe.db.set_value(doctype, name, "creation", stamp, update_modified=False)
		frappe.db.set_value(
			"Course Registration", doc.name, "program_enrollment", None, update_modified=False
		)
		return doc.name, first, second

	def bound(self, name):
		return frappe.db.get_value("Course Registration", name, "program_enrollment")

	def test_a_reenrolled_student_is_bound_to_the_enrollment_of_its_own_date(self):
		name, first, _second = self.legacy_registration(5)
		patch.bind_registrations()
		self.assertEqual(self.bound(name), first)

	def test_a_cancelled_registration_is_bound_the_same_way(self):
		name, first, _second = self.legacy_registration(4)
		frappe.db.set_value("Course Registration", name, "docstatus", 2, update_modified=False)
		patch.bind_registrations()
		self.assertEqual(self.bound(name), first)

	def test_a_registration_older_than_every_enrollment_is_reported_and_left_blank(self):
		name, _first, _second = self.legacy_registration(3, **{})
		frappe.db.set_value(
			"Course Registration", name, "creation", "2020-01-01 00:00:00", update_modified=False
		)
		self.assertIn(name, patch.bind_registrations())
		self.assertFalse(self.bound(name))

	def test_a_date_outside_every_academic_year_is_reported_and_left_blank(self):
		name, _first, _second = self.legacy_registration(2)
		frappe.db.set_value(
			"Course Registration", name, "registration_date", "2030-01-01", update_modified=False
		)
		self.assertIn(name, patch.bind_registrations())
		self.assertFalse(self.bound(name))

	def test_bound_registrations_are_left_alone(self):
		doc = self.regular("REG C", student=1)
		patch.bind_registrations()
		self.assertEqual(self.bound(doc.name), doc.program_enrollment)
