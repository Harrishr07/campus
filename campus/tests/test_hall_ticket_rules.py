"""M06-02 unit tests: why a hall ticket is withheld (hall_ticket_rules.withheld_reasons), every branch."""

from frappe.tests import UnitTestCase

from campus.examinations.hall_ticket_rules import withheld_reasons


def reasons(**overrides):
	facts = {"confirmed": True, "dues": 0, "debarred": None, "detained": None, "shortage": False, "eligible_courses": 2}
	return withheld_reasons(**{**facts, **overrides})


class TestWithheldReasons(UnitTestCase):
	def test_a_confirmed_eligible_student_without_dues_gets_a_ticket(self):
		self.assertEqual(reasons(), [])

	def test_unconfirmed_registration(self):
		self.assertEqual(reasons(confirmed=False), ["Exam registration not confirmed"])

	def test_unpaid_exam_dues(self):
		self.assertEqual(reasons(dues=1100), ["Unpaid exam dues of 1,100.00"])

	def test_debarment_withholds_with_its_reason(self):
		self.assertEqual(reasons(debarred="Malpractice", eligible_courses=0), ["Debarred: Malpractice"])

	def test_shortage_or_detention_withholds_only_when_no_course_is_left(self):
		self.assertEqual(reasons(shortage=True, eligible_courses=0), ["Attendance shortage (SA)"])
		self.assertEqual(reasons(detained="Committee order", eligible_courses=0), ["Detained: Committee order"])
		self.assertEqual(
			reasons(shortage=True, detained="Committee order", eligible_courses=0),
			["Attendance shortage (SA)", "Detained: Committee order"],
		)
		# R2022 cl. 15.1: an SA or detained student still sits the eligible arrears
		self.assertEqual(reasons(shortage=True, detained="Committee order", eligible_courses=1), [])

	def test_no_eligible_course_without_a_flag(self):
		self.assertEqual(reasons(eligible_courses=0), ["No course is eligible for the examination"])

	def test_every_reason_is_listed(self):
		self.assertEqual(
			reasons(confirmed=False, dues=500, debarred="Malpractice", shortage=True, eligible_courses=0),
			["Debarred: Malpractice", "Exam registration not confirmed", "Unpaid exam dues of 500.00"],
		)
