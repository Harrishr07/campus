"""M05-03 integration tests: Rejoin Application moves the student to the regulation of the cohort rejoined (through
the P1-T05 regulation history) and to that cohort's batch, checked again at submit; offered bridge courses are
registered as Bridge and graded by the Result Run, unoffered ones stay pending."""

import frappe

from campus.examinations import registration, results
from campus.examinations.seed import seed_regulation
from campus.student_services.api import pending_bridge_courses
from campus.tests.test_regulation import make_regulation, year_name
from campus.tests.test_results import COLLEGE, PROGRAM, enter_marks, make_course, make_curriculum, make_offering
from campus.tests.test_student_records import CLERK, REJOIN, StudentRecordsFixture

BRIDGE_COURSE = "EXM BRIDGE"
EXTRA_YEARS = ("2023", "2024", "2025", "2027")


def make_academic_year(year):
	if not frappe.db.exists("Academic Year", year_name(year)):
		frappe.get_doc(
			{
				"doctype": "Academic Year", "academic_year_name": year_name(year),
				"year_start_date": f"{year}-06-01", "year_end_date": f"{int(year) + 1}-05-31",
			}
		).insert()  # fmt: skip


class TestRejoin(StudentRecordsFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for year in EXTRA_YEARS:
			make_academic_year(year)
		cls.r2024 = make_regulation("R2024-EXM", COLLEGE, [PROGRAM], "2024").name
		seed_regulation(cls.r2024, "R2022")
		make_course(BRIDGE_COURSE)
		cls.bridge_curriculum = make_curriculum(cls.r2024, {BRIDGE_COURSE: ("Theory", 0, 3)})

	def rejoin(self, study_break, year="2026", rejoin_date="2026-06-15", bridge=(BRIDGE_COURSE,)):
		frappe.set_user(CLERK)
		doc = frappe.get_doc(
			{
				"doctype": REJOIN, "break_of_study": study_break.name, "rejoin_date": rejoin_date,
				"academic_year": year_name(year), "bridge_courses": [{"course": c} for c in bridge],
			}
		).insert()  # fmt: skip
		frappe.set_user("Administrator")
		return doc

	def two_year_break(self, student, start="2024-06-01", end="2026-05-31"):
		return self.approve_fully(self.study_break(student, start, end, exceptional=1, exceptional_reason="Surgery"))

	def test_a_rejoiner_takes_the_regulation_and_batch_of_the_cohort_joined(self):
		# admitted 2022, two years done when the break starts in 2024, back in 2026: joins the 2024 cohort (R2024),
		# not the regulation of a 2026 admission (R2026)
		old = frappe.db.get_value("Student", self.s22.name, "oc_regulation")
		doc = self.rejoin(self.two_year_break(self.s22))
		self.assertEqual((doc.from_regulation, doc.to_regulation), (old, self.r2024))
		self.assertEqual((doc.from_batch, doc.to_batch), (year_name("2022"), year_name("2024")))
		self.approve_fully(doc)
		student = frappe.get_doc("Student", self.s22.name)
		self.assertEqual((student.oc_regulation, student.oc_batch), (self.r2024, year_name("2024")))
		self.assertEqual(student.oc_academic_status, "Active")
		history = student.oc_regulation_history[-1]
		self.assertEqual((history.from_regulation, history.to_regulation), (old, self.r2024))
		self.assertIn(doc.name, history.reason)
		self.assertIn(BRIDGE_COURSE, history.bridge_courses_note)

	def test_the_rejoin_date_must_fall_in_the_academic_year(self):
		with self.assertRaisesRegex(frappe.ValidationError, "academic year"):
			self.rejoin(self.two_year_break(self.s22), rejoin_date="2025-12-01")

	def test_a_tampered_regulation_is_refused_at_submit(self):
		doc = self.rejoin(self.two_year_break(self.s22))
		r2026 = frappe.db.get_value("Regulation", {"code": "R2026-EXM"})
		frappe.db.set_value(REJOIN, doc.name, "to_regulation", r2026)
		with self.assertRaisesRegex(frappe.ValidationError, "changed"):
			self.approve_fully(doc)
		self.assertEqual(frappe.db.get_value("Student", self.s22.name, "oc_regulation"), doc.from_regulation)

	def test_an_offered_bridge_course_is_registered_and_graded_an_unoffered_one_stays_pending(self):
		self.approve_fully(self.rejoin(self.two_year_break(self.s22)))
		frappe.get_doc(
			{"doctype": "Attendance Eligibility Run", "company": COLLEGE, "academic_term": self.term, "locked": 1,
				"rows": [{"student": self.s22.name, "status": "Eligible"}]}
		).insert()  # fmt: skip
		name = registration.register(self.s22.name, self.session.name)
		courses = {r.course for r in frappe.get_doc("Exam Registration", name).courses}
		self.assertNotIn(BRIDGE_COURSE, courses)  # not offered: not registered, not charged
		self.assertEqual(pending_bridge_courses(self.s22.name), [BRIDGE_COURSE])
		offering = make_offering(BRIDGE_COURSE, self.bridge_curriculum, self.term, [self.s22.name])
		enter_marks(self.session.name, offering, {self.s22.name: (30, 40)})
		registration.register(self.s22.name, self.session.name)
		rows = {r.course: (r.kind, r.eligibility) for r in frappe.get_doc("Exam Registration", name).courses}
		self.assertEqual(rows[BRIDGE_COURSE], ("Bridge", "Eligible"))
		results.compute_student_result(self.s22.name, self.session.name)
		graded = {c.course: c.result for c in frappe.get_doc("Student Result", f"SR-{self.session.name}-{self.s22.name}").courses}
		self.assertEqual(graded[BRIDGE_COURSE], "Pass")  # 70%
		self.assertEqual(pending_bridge_courses(self.s22.name), [])

	def test_a_rejoin_needs_an_approved_break_and_only_one_per_break(self):
		draft = self.study_break(self.s22, "2025-06-01", "2026-05-31")
		with self.assertRaisesRegex(frappe.ValidationError, "approved"):
			self.rejoin(draft)
		self.approve_fully(draft)
		self.approve_fully(self.rejoin(draft))
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			self.rejoin(draft)

	def test_a_rejoin_on_the_same_regulation_keeps_it_and_restores_the_status(self):
		frappe.db.set_value("Student", self.s26.name, "oc_academic_status", "Long Absent")
		before = len(frappe.get_doc("Student", self.s26.name).oc_regulation_history)
		study_break = self.approve_fully(self.study_break(self.s26, "2026-06-01", "2027-05-31"))
		doc = self.approve_fully(self.rejoin(study_break, year="2027", rejoin_date="2027-06-15", bridge=()))
		self.assertEqual(doc.from_regulation, doc.to_regulation)
		student = frappe.get_doc("Student", self.s26.name)
		self.assertEqual(len(student.oc_regulation_history), before)
		self.assertEqual(student.oc_academic_status, "Long Absent")  # the status before the break

	def test_a_break_before_admission_has_no_cohort(self):
		study_break = self.approve_fully(self.study_break(self.s26, "2025-06-01", "2026-05-31"))  # batch 2026
		with self.assertRaisesRegex(frappe.ValidationError, "admission"):
			self.rejoin(study_break)
