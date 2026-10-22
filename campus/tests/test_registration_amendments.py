"""R-05 integration tests (M03-08): a registration is bound to its own Program Enrollment, term credits
are cumulative over active registrations, and the window deadline holds for amendments of drafts."""

import frappe
from frappe.utils import add_days, today

from campus.tests.test_registration import COLLEGE, PROGRAM, RegistrationTestCase
from campus.tests.factories import make_user
from campus.tests.test_regulation import enroll, make_year

RE_ENROLMENT_YEARS = iter(("2020", "2021", "2023", "2026"))  # years make_year knows; the first enrolment is 2022


class TestEnrollmentBinding(RegistrationTestCase):
	def program_enrollments(self, student):
		return frappe.get_all(
			"Program Enrollment", {"student": self.students[student].name}, pluck="name", order_by="creation"
		)

	def course_enrollments(self, student, course):
		return frappe.get_all(
			"Course Enrollment",
			{"student": self.students[student].name, "course": course},
			pluck="program_enrollment",
		)

	def re_enroll(self, student):
		"""Enroll the student again, in a year not used before."""
		year = next(RE_ENROLMENT_YEARS)
		make_year(year)
		return enroll(self.students[student], PROGRAM, year).name

	def test_registration_stores_the_enrollment_it_was_made_for(self):
		doc = self.regular("REG C", student=4)
		self.assertEqual(doc.program_enrollment, self.program_enrollments(4)[-1])

	def test_apply_uses_the_stored_enrollment_not_the_latest(self):
		doc = self.regular("REG C", student=4)
		original = doc.program_enrollment
		self.re_enroll(4)
		doc.submit()
		self.assertEqual(self.course_enrollments(4, "REG C"), [original])

	def test_cancel_removes_only_its_own_enrollment_rows(self):
		doc = self.regular("REG C", student=4)
		original = doc.program_enrollment
		doc.submit()
		newer = self.re_enroll(4)
		frappe.get_doc(
			{
				"doctype": "Course Enrollment", "student": self.students[4].name, "course": "REG C",
				"program_enrollment": newer, "enrollment_date": today(),
			}
		).insert()
		doc.cancel()
		self.assertEqual(self.course_enrollments(4, "REG C"), [newer])
		self.assertNotIn(original, self.course_enrollments(4, "REG C"))

	def test_bound_enrollment_cannot_change_after_creation(self):
		doc = self.regular("REG C", student=4)
		doc.program_enrollment = self.re_enroll(4)
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_enrollment_of_another_student_is_refused(self):
		other = self.program_enrollments(3)[0]
		with self.assertRaisesRegex(frappe.ValidationError, "not an enrollment of"):
			self.regular("REG C", student=4, program_enrollment=other)


class TestCumulativeCredits(RegistrationTestCase):
	def test_second_registration_counts_credits_already_registered(self):
		self.regular("REG A", student=3).submit()  # 18
		with self.assertRaisesRegex(frappe.ValidationError, r"39 credits registered; the maximum is 36"):
			self.regular("REG B", "REG C", student=3)  # 18 + 3 on top of 18

	def test_cumulative_total_up_to_the_limit_is_accepted(self):
		self.regular("REG A", student=3).submit()
		doc = self.regular("REG B", student=3)
		self.assertEqual(doc.total_credits, 18)  # this registration's own credits

	def test_drafts_do_not_count(self):
		self.regular("REG A", student=3)
		self.assertEqual(self.regular("REG B", student=3).docstatus, 0)

	def test_cancelled_registrations_do_not_count(self):
		first = self.regular("REG A", student=3)
		first.submit()
		first.cancel()
		self.assertEqual(self.regular("REG B", "REG C", student=3).total_credits, 21)

	def test_excluded_types_stay_excluded_cumulatively(self):
		self.registration([("REG A", "Regular"), ("REG B", "Regular")], student=3).submit()
		self.assertEqual(self.registration([("REG E", "Arrear")], student=3).total_credits, 0)

	def test_other_students_credits_do_not_count(self):
		self.regular("REG A", "REG B", student=2).submit()
		self.assertEqual(self.regular("REG A", student=3).docstatus, 0)

	def test_two_drafts_cannot_both_be_submitted_past_the_limit(self):
		one = self.regular("REG A", student=3)
		two = self.regular("REG B", "REG C", student=3)
		one.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "39 credits registered"):
			two.submit()

	def test_window_cap_applies_to_the_cumulative_total(self):
		self.window.db_set("max_credits", 20)
		self.regular("REG A", student=3).submit()
		with self.assertRaisesRegex(frappe.ValidationError, "the maximum is 20"):
			self.regular("REG C", "REG D", student=3, date="2022-06-10").submit()  # 18 + 6 > 20


class TestAmendmentDeadline(RegistrationTestCase):
	def open_window_around_today(self):
		self.window.db_set({"opens_on": add_days(today(), -3), "closes_on": add_days(today(), 3)})

	def close_window(self):
		self.window.db_set({"opens_on": add_days(today(), -10), "closes_on": add_days(today(), -1)})

	def draft(self):
		self.open_window_around_today()
		return self.regular("REG C", date=today())

	def test_draft_can_be_edited_while_the_window_is_open(self):
		doc = self.draft()
		doc.append("items", {"course": "REG D", "registration_type": "Regular"})
		doc.save()
		self.assertEqual(len(doc.items), 2)

	def test_draft_cannot_be_edited_after_the_window_closes(self):
		doc = self.draft()
		self.close_window()
		doc.append("items", {"course": "REG D", "registration_type": "Regular"})
		with self.assertRaisesRegex(frappe.ValidationError, "not open"):
			doc.save()

	def test_draft_saved_unchanged_after_close_is_refused_too(self):
		doc = self.draft()
		self.close_window()
		with self.assertRaisesRegex(frappe.ValidationError, "not open"):
			doc.save()

	def test_submit_after_close_is_allowed_for_a_draft_made_in_time(self):
		doc = self.draft()
		self.close_window()
		doc.submit()
		self.assertEqual(doc.docstatus, 1)

	def test_dropping_after_close_is_governed_by_the_drop_deadline_only(self):
		self.regular("REG C", student=2).submit()
		self.close_window()
		self.window.db_set("drop_until", add_days(today(), 5))
		drop = self.registration([("REG C", "Dropped")], student=2, date=today())
		drop.save()
		self.assertEqual(drop.docstatus, 0)


class TestLateRegistration(RegistrationTestCase):
	def setUp(self):
		super().setUp()
		self.window.db_set({"opens_on": add_days(today(), -10), "closes_on": add_days(today(), -1)})

	def late(self, user="Administrator", **extra):
		frappe.set_user(user)
		return self.regular("REG C", date=today(), **extra)

	def test_late_registration_without_a_reason_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "not open"):
			self.late()

	def test_authorised_late_registration_keeps_approver_and_reason(self):
		doc = self.late(late_reason="Medical leave in the window")
		doc.reload()
		self.assertEqual((doc.late_approved_by, doc.late_reason), ("Administrator", "Medical leave in the window"))

	def test_user_without_the_late_role_cannot_authorise(self):
		make_user("reg-late-clerk@example.com", [COLLEGE])
		with self.assertRaisesRegex(frappe.ValidationError, "not open"):
			self.late("reg-late-clerk@example.com", late_reason="Because")

	def test_approver_cannot_be_forged_by_the_caller(self):
		make_user("reg-late-clerk@example.com", [COLLEGE])
		with self.assertRaisesRegex(frappe.ValidationError, "not open"):
			self.late("reg-late-clerk@example.com", late_reason="Because", late_approved_by="Administrator")

	def test_later_edit_by_another_user_keeps_the_original_approver(self):
		doc = self.late(late_reason="Medical leave in the window")
		make_user("reg-late-clerk@example.com", [COLLEGE])
		frappe.set_user("reg-late-clerk@example.com")
		doc = frappe.get_doc("Course Registration", doc.name)
		doc.save()
		self.assertEqual(doc.late_approved_by, "Administrator")

	def test_in_window_registration_carries_no_late_approver(self):
		self.window.db_set({"opens_on": add_days(today(), -3), "closes_on": add_days(today(), 3)})
		doc = self.regular("REG C", date=today(), late_reason="x", late_approved_by="Administrator")
		self.assertFalse(doc.late_approved_by)
