"""M06-05 integration test of the Result Run at scale (P2-T19 AC1): two programmes, an R2022 batch graded
relatively (Box-Cox, cohort above 30) and an R2026 batch graded absolutely, run through the bulk handler,
with 20 sampled students checked against hand-computed grades and the run time extrapolated to 480 students.

Marks of student i (0-44) of each batch: EXM TH (theory, CIA 40 + ESE 60) CIA 18 + 7i mod 23, ESE 20 + 11i mod 41;
EXM LB (lab, CIA 60 + ESE 40) CIA 30 + 5i mod 31, ESE 15 + 3i mod 26. Pass: ESE >= 45 % and total >= 50 %.
"""

import json
import os
import time
import unittest
from unittest.mock import patch

import frappe

from campus.examinations import api, publication, results
from campus.examinations.result_cohort import Cohorts
from campus.examinations.rules import RELATIVE, relative_grade, relative_grade_bands
from campus.tests.test_regulation import enroll, make_program, make_student, year_name
from campus.tests.test_results import COE_USER, COLLEGE, COURSES, PROGRAM, ExamFixture

PROGRAM2 = "Exam Test BE ECE"
BATCH = 45
TARGET_STUDENTS, TARGET_SECONDS = 480, 600

# i -> ((TH letter, point), (LB letter, point), SGPA): R2026 absolute, hand-computed from the marks above
R2026_EXPECTED = {
	0: (("U", 0), ("U", 0), 0),  # TH 18+20 = 38; LB ESE 15 < 18
	1: (("C+", 6), ("C", 5), 5.6),  # 25+31 = 56; 35+18 = 53; (18 + 10) / 5
	2: (("A", 8), ("B", 6.5), 7.4),  # 32+42 = 74; 40+21 = 61
	3: (("S", 10), ("B+", 7), 8.8),  # 39+53 = 92; 45+24 = 69
	4: (("U", 0), ("A", 8), 8.0),  # ESE 23 < 27; 50+27 = 77
	5: (("B", 6.5), ("A+", 9), 7.5),  # 30+34 = 64; 55+30 = 85
	6: (("A+", 9), ("S", 10), 9.4),  # 37+45 = 82; 60+33 = 93
	7: (("A", 8), ("B+", 7), 7.6),  # 21+56 = 77; 34+36 = 70
	8: (("U", 0), ("A", 8), 8.0),  # total 54 but ESE 26 < 27; 39+39 = 78
	9: (("A", 8), ("U", 0), 8.0),  # 35+37 = 72; LB ESE 16 < 18
}
# R2022 lab rows (absolute), hand-computed: i -> (letter, point)
R2022_LAB_EXPECTED = {
	0: ("U", 0), 1: ("C", 5), 2: ("B+", 7), 3: ("B+", 7), 4: ("A", 8),
	5: ("A+", 9), 6: ("O", 10), 7: ("B+", 7), 8: ("A", 8), 9: ("U", 0),
}  # fmt: skip


def theory_marks(i):
	return 18 + (i * 7) % 23, 20 + (i * 11) % 41


def lab_marks(i):
	return 30 + (i * 5) % 31, 15 + (i * 3) % 26


class ScaleFixture(ExamFixture):
	"""Two programmes of `batch_size` students each. No tests here: a test class must not be subclassed, as Frappe
	sets up (and rolls back) a class once and a subclass would inherit that flag and leak its data."""

	batch_size = BATCH

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_program(PROGRAM2, COLLEGE)
		for name in frappe.get_all(
			"Curriculum", {"program": PROGRAM2}, pluck="name"
		):  # clear_world clears PROGRAM's only
			frappe.db.delete("Curriculum Course", {"parent": name})
			frappe.db.delete("Curriculum", {"name": name})
		regulation26 = frappe.db.get_value("Student", cls.s26.name, "oc_regulation")
		regulation = frappe.get_doc(
			"Regulation", regulation26
		)  # Effective: add the programme row without a save
		regulation.append("programs", {"program": PROGRAM2}).db_insert()
		curriculum2 = frappe.get_doc(
			{
				"doctype": "Curriculum", "program": PROGRAM2, "regulation": regulation26, "status": "Draft",
				"courses": [
					{"semester": 1, "course": c, "category": "PCC", "exam_type": COURSES[c][0], "practical_periods": COURSES[c][1],
					"credits_override": 1, "credits": COURSES[c][2]}
					for c in ("EXM TH", "EXM LB")
				],
			}
		).insert().name  # fmt: skip
		cls.batch22 = [cls.student(f"Scl22n{i:02d}", "2022", PROGRAM) for i in range(cls.batch_size)]
		cls.batch26 = [cls.student(f"Scl26n{i:02d}", "2026", PROGRAM2) for i in range(cls.batch_size)]
		for course, marks in (("EXM TH", theory_marks), ("EXM LB", lab_marks)):
			for program, curriculum, batch in (
				(PROGRAM, cls.curriculum22, cls.batch22),
				(PROGRAM2, curriculum2, cls.batch26),
			):
				offering = cls.offering(course, program, curriculum, batch)
				frappe.get_doc(
					{"doctype": "Mark Sheet Entry", "exam_session": cls.session.name, "course_offering": offering,
					"marks": [{"student": s, "cia": marks(i)[0], "ese": marks(i)[1]} for i, s in enumerate(batch)]}
				).insert()  # fmt: skip

	@classmethod
	def student(cls, first_name, batch, program):
		student = make_student(first_name, COLLEGE, batch)
		enroll(student, program, "2022", submit=True)
		return student.name

	@classmethod
	def offering(cls, course, program, curriculum, students):
		return frappe.get_doc(
			{
				"doctype": "Student Group", "student_group_name": f"SCL-{course}-{program}", "group_based_on": "Course",
				"academic_year": year_name("2022"), "academic_term": cls.term, "program": program, "course": course,
				"oc_company": COLLEGE, "oc_curriculum": curriculum, "oc_semester": 1, "students": [{"student": s} for s in students],
			}
		).insert().name  # fmt: skip

	def run_programs(self):
		"""Queue each programme's Result Run as the COE and process its items through the bulk handler."""
		frappe.set_user(COE_USER)
		with patch("campus.campus_platform.bulk.enqueue_run"):
			runs = [
				frappe.get_doc("Bulk Run", api.run_results(self.session.name, p)) for p in (PROGRAM, PROGRAM2)
			]
		frappe.set_user("Administrator")
		started, count = time.monotonic(), 0
		for run in runs:
			for student in frappe.parse_json(run.items):
				results.run_student(student, run)
				count += 1
		return count, time.monotonic() - started

	def result(self, student):
		name = frappe.db.get_value(
			"Student Result", {"student": student, "exam_session": self.session.name, "is_latest": 1}
		)
		return frappe.get_doc("Student Result", name)

	def course(self, student, course):
		return next(c for c in self.result(student).courses if c.course == course)


class TestResultRunAtScale(ScaleFixture):
	def test_two_programmes_process_well_within_the_time_budget(self):
		count, seconds = self.run_programs()
		self.assertEqual(count, 2 * BATCH + 4)  # both batches and the four fixture students
		self.assertLess(
			seconds / count * TARGET_STUDENTS, TARGET_SECONDS
		)  # the measured 480 run: TestResultRunOf480

	def test_twenty_sampled_students_match_the_hand_computed_fixture(self):
		self.run_programs()
		for i, (theory, lab, sgpa) in R2026_EXPECTED.items():
			student = self.batch26[i]
			got = (self.course(student, "EXM TH"), self.course(student, "EXM LB"))
			self.assertEqual([(c.grade, c.grade_point) for c in got], [theory, lab], f"R2026 student {i}")
			self.assertEqual({c.grading_method for c in got if c.result == "Pass"} - {"Absolute"}, set())
			self.assertEqual(
				(self.result(student).sgpa, self.result(student).cgpa), (sgpa, sgpa), f"R2026 student {i}"
			)
		for i, lab in R2022_LAB_EXPECTED.items():
			row = self.course(self.batch22[i], "EXM LB")
			self.assertEqual((row.grade, row.grade_point), lab, f"R2022 student {i}")

	def test_r2022_theory_is_graded_relatively_in_monotone_bands(self):
		self.run_programs()
		rows = [self.course(s, "EXM TH") for s in self.batch22]
		passed = [r for r in rows if r.result == "Pass"]
		self.assertEqual(len(passed), 36)  # 9 of 45 fail on the ESE or the total
		self.assertEqual({r.grading_method for r in passed}, {RELATIVE})
		# a higher total never gets a lower grade point, and the bands differ from the absolute table somewhere
		ordered = sorted(passed, key=lambda r: r.total)
		self.assertEqual([r.grade_point for r in ordered], sorted(r.grade_point for r in ordered))
		absolute = {r.name: results.rules.grade(r.total, self.r2022_grades()) for r in passed}
		self.assertTrue(any((r.grade, r.grade_point) != absolute[r.name] for r in passed))
		self.assertEqual({r.grading_method or "" for r in rows if r.result != "Pass"}, {""})

	def test_r2022_theory_letters_follow_bands_of_independently_computed_totals(self):
		self.run_programs()
		# the cohort: the 36 passing students of the batch and the fixture's s22 (28 + 35 = 63); s_ab is absent and
		# s_sa short of attendance. Totals out of 100 are CIA + ESE.
		totals = [
			sum(theory_marks(i))
			for i in range(BATCH)
			if theory_marks(i)[1] >= 27 and sum(theory_marks(i)) >= 50
		] + [63]
		bands = relative_grade_bands(totals, self.r2022_grades())
		for i, student in enumerate(self.batch22):
			cia, ese = theory_marks(i)
			if ese >= 27 and cia + ese >= 50:
				row = self.course(student, "EXM TH")
				self.assertEqual(
					(row.grade, row.grade_point), relative_grade(cia + ese, bands), f"R2022 student {i}"
				)

	def test_bands_are_frozen_at_publication_for_later_reruns(self):
		self.run_programs()
		frozen = publication.freeze_bands(self.session.name)
		frappe.db.set_value(
			"Exam Session",
			self.session.name,
			{"status": "Published", "publish_at": frappe.utils.add_days(frappe.utils.now_datetime(), -1)},
		)
		stored = json.loads(frappe.db.get_value("Exam Session", self.session.name, "frozen_bands"))
		self.assertEqual(stored, frozen)
		scheme = frappe.db.get_value(
			"Grading Scheme", {"regulation": frappe.db.get_value("Student", self.s22.name, "oc_regulation")}
		)
		key = publication.band_key("EXM TH", scheme)
		self.assertIn(key, stored)
		before = {s: self.course(s, "EXM TH").grade for s in self.batch22}
		sheet_rows = frappe.get_all(
			"Mark Sheet Entry Row",
			{
				"student": ["in", self.batch22[:10]],
				"parent": ["in", frappe.get_all("Mark Sheet Entry", {"course": "EXM TH"}, pluck="name")],
			},
			pluck="name",
		)
		for name in sheet_rows:  # ten revaluations to full marks would move live bands
			frappe.db.set_value("Mark Sheet Entry Row", name, "ese", 60)
		live = Cohorts(self.session.name, lambda student: False).totals("EXM TH", scheme)
		self.assertNotEqual(relative_grade_bands(live, self.r2022_grades()), stored[key])
		for student in self.batch22:
			results.compute_student_result(student, self.session.name)
		for i, student in enumerate(self.batch22):
			pending = frappe.db.get_value(
				"Student Result",
				{"student": student, "exam_session": self.session.name, "pending_ratification": 1},
			)
			if i >= 10:  # unchanged marks: no new version, whatever the live cohort became
				self.assertIsNone(pending, f"R2022 student {i}")
				self.assertEqual(self.course(student, "EXM TH").grade, before[student])
			else:
				row = next(
					c for c in frappe.get_doc("Student Result", pending).courses if c.course == "EXM TH"
				)
				self.assertEqual(
					(row.grade, row.grade_point), relative_grade(row.total, stored[key]), f"R2022 student {i}"
				)

	def test_publication_freezes_the_bands_the_run_graded_on(self):
		self.run_programs()
		scheme = frappe.db.get_value(
			"Grading Scheme", {"regulation": frappe.db.get_value("Student", self.s22.name, "oc_regulation")}
		)
		key = publication.band_key("EXM TH", scheme)
		recorded = json.loads(
			frappe.db.get_value("Exam Session", self.session.name, "frozen_bands")
		)  # stored by the run
		totals = [
			sum(theory_marks(i))
			for i in range(BATCH)
			if theory_marks(i)[1] >= 27 and sum(theory_marks(i)) >= 50
		] + [63]
		self.assertEqual(recorded[key], relative_grade_bands(totals, self.r2022_grades()))
		self.assertEqual(set(recorded), {key})  # labs and the R2026 batch are absolute
		sheets = frappe.get_all("Mark Sheet Entry", {"course": "EXM TH"}, pluck="name")
		for name in frappe.get_all(
			"Mark Sheet Entry Row",
			{"student": ["in", self.batch22[:10]], "parent": ["in", sheets]},
			pluck="name",
		):
			frappe.db.set_value(
				"Mark Sheet Entry Row", name, "ese", 60
			)  # changed after the run, never re-run
		self.assertEqual(publication.freeze_bands(self.session.name)[key], recorded[key])

	def r2022_grades(self):
		scheme = frappe.get_doc(
			"Grading Scheme", {"regulation": frappe.db.get_value("Student", self.s22.name, "oc_regulation")}
		)
		return [g.as_dict() for g in scheme.grades]


@unittest.skipUnless(os.environ.get("CAMPUS_SLOW_TESTS"), "480-student timing run: set CAMPUS_SLOW_TESTS=1")
class TestResultRunOf480(ScaleFixture):
	"""AC1 evidence: 2 x 238 batch students + the 4 fixture students = 480, attendance eligibility computed for
	real (not patched; Attendance Rules on both regulations, no periods conducted)."""

	batch_size = (TARGET_STUDENTS - 4) // 2

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for student in (cls.s22, cls.s26):
			regulation = frappe.db.get_value("Student", student.name, "oc_regulation")
			if not frappe.db.exists("Attendance Rule", {"regulation": regulation}):
				frappe.get_doc(
					{"doctype": "Attendance Rule", "regulation": regulation, "formula": "course_average",
					"overall_min_pct": 75, "medical_band_min_pct": 65, "per_course_min_pct": 75}
				).insert()  # fmt: skip
		for (
			offering
		) in cls.offerings22.values():  # s_sa is no longer short of attendance here: it needs marks
			sheet = frappe.get_doc("Mark Sheet Entry", {"course_offering": offering})
			sheet.append("marks", {"student": cls.s_sa.name, "cia": 30, "ese": 40})
			sheet.save()

	def setUp(self):  # the fixture's savepoint, without its eligibility patch
		frappe.db.savepoint("exam_test")
		self.addCleanup(frappe.db.rollback, save_point="exam_test")
		self.addCleanup(frappe.set_user, "Administrator")

	def test_480_students_run_in_under_ten_minutes(self):
		count, seconds = self.run_programs()
		self.assertEqual(count, TARGET_STUDENTS)
		print(
			f"\nResult Run of {count} students: {seconds:.1f}s ({seconds / count * 1000:.0f} ms each)"
		)  # recorded in the T19 report
		self.assertLess(seconds, TARGET_SECONDS)
