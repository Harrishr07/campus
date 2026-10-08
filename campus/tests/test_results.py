"""M12-02 integration test: marks entry, Result Run, grades under two regulations, SGPA/CGPA, publication access."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, now_datetime

from campus.campus_platform import bulk
from campus.campus_platform.verification import verify
from campus.examinations import api, results
from campus.examinations.seed import seed_regulation
from campus.tests.broadcast_fixtures import make_guardian
from campus.tests.factories import make_company, make_user
from campus.tests.test_regulation import enroll, make_program, make_regulation, make_student, make_year, year_name
from campus.tests.utils import CampusTestCase

COLLEGE = "Exam Test College"
PROGRAM = "Exam Test BE"
PRE_TERM, TERM = "Exm Pre", "Exm Odd"
COE_USER = "exam-coe@example.com"
FACULTY, OTHER_FACULTY = "exam-faculty@example.com", "exam-other-faculty@example.com"
STUDENT_22_USER, STUDENT_26_USER, GUARDIAN_USER = (
	"exam-s22@example.com", "exam-s26@example.com", "exam-guardian@example.com",
)  # fmt: skip
# course -> (exam type, practical periods, credits)
COURSES = {
	"EXM TH": ("Theory", 0, 3), "EXM LB": ("Practical", 2, 2), "EXM TL": ("Theory", 2, 4), "EXM FA": ("Theory", 0, 3),
}  # fmt: skip
PRE_COURSE = ("EXM PRE", ("Theory", 0, 4))
# the same raw marks for every student: (CIA, ESE); totals 63, 75, 85 and a fail at ESE 44% / total 60
MARKS = {"EXM TH": (28, 35), "EXM LB": (45, 30), "EXM TL": (40, 45), "EXM FA": (33.6, 26.4)}


def clear_world():
	students = frappe.get_all("Student", {"oc_company": COLLEGE}, pluck="name") or [""]
	frappe.db.delete("Student Result Course", {"parenttype": "Student Result", "parent": ["like", "SR-EXS-%"]})
	frappe.db.delete("Student Result", {"student": ["in", students]})
	entries = frappe.get_all("Mark Sheet Entry", {"company": COLLEGE}, pluck="name") or [""]
	frappe.db.delete("Mark Sheet Entry Row", {"parent": ["in", entries]})
	frappe.db.delete("Mark Sheet Entry", {"name": ["in", entries]})
	frappe.db.delete("Exam Session", {"company": COLLEGE})
	groups = frappe.get_all("Student Group", {"oc_company": COLLEGE}, pluck="name") or [""]
	frappe.db.delete("Student Group Instructor", {"parent": ["in", groups]})
	frappe.db.delete("Student Group Student", {"parent": ["in", groups]})
	frappe.db.delete("Student Group", {"name": ["in", groups]})
	frappe.db.delete("Guardian", {"guardian_name": "Examguardian"})
	frappe.db.delete("Student Guardian", {"parent": ["in", students]})
	frappe.db.delete("Program Enrollment", {"student": ["in", students]})
	frappe.db.delete("Student", {"name": ["in", students]})
	for name in frappe.get_all("Curriculum", {"program": PROGRAM}, pluck="name"):
		frappe.db.delete("Curriculum Course", {"parent": name})
		frappe.db.delete("Curriculum", {"name": name})
	frappe.db.delete("Grading Scheme", {"regulation": ["like", "%-EXM"]})
	frappe.db.delete("Exam Rule Set", {"regulation": ["like", "%-EXM"]})


def make_term(name, start, end):
	found = frappe.db.get_value("Academic Term", {"academic_year": year_name("2022"), "term_name": name})
	return found or frappe.get_doc(
		{
			"doctype": "Academic Term", "academic_year": year_name("2022"), "term_name": name,
			"term_start_date": start, "term_end_date": end,
		}
	).insert().name  # fmt: skip


def make_login(email, role):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
			"roles": [{"role": role}]}
		).insert()  # fmt: skip


def make_instructor(email):
	if not frappe.db.exists("Gender", "Female"):  # a fresh site has no Gender records
		frappe.get_doc({"doctype": "Gender", "gender": "Female"}).insert()
	employee = frappe.get_doc(
		{
			"doctype": "Employee", "naming_series": "HR-EMP-", "first_name": email.split("@")[0], "gender": "Female",
			"date_of_birth": "1985-01-01", "date_of_joining": "2020-06-01", "status": "Active", "company": COLLEGE,
			"user_id": email, "create_user_permission": 0,
		}
	).insert()  # fmt: skip
	return frappe.get_doc(
		{"doctype": "Instructor", "instructor_name": email, "employee": employee.name, "oc_company": COLLEGE}
	).insert().name  # fmt: skip


def make_curriculum(regulation, courses):
	rows = [
		{
			"semester": 1, "course": course, "category": "PCC", "exam_type": kind, "practical_periods": practical,
			"credits_override": 1, "credits": credits,
		}
		for course, (kind, practical, credits) in courses.items()
	]  # fmt: skip
	return frappe.get_doc(
		{"doctype": "Curriculum", "program": PROGRAM, "regulation": regulation, "status": "Draft", "courses": rows}
	).insert().name  # fmt: skip


def make_course(course):
	if not frappe.db.exists("Course", course):
		frappe.get_doc({"doctype": "Course", "course_name": course, "oc_company": COLLEGE}).insert()


def make_offering(course, curriculum, term, students, instructor=None):
	doc = frappe.get_doc(
		{
			"doctype": "Student Group", "student_group_name": f"{course}-{curriculum}-{term}", "group_based_on": "Course",
			"academic_year": year_name("2022"), "academic_term": term, "program": PROGRAM, "course": course,
			"oc_company": COLLEGE, "oc_curriculum": curriculum, "oc_semester": 1,
			"students": [{"student": s} for s in students],
			"instructors": [{"instructor": instructor}] if instructor else [],
		}
	)  # fmt: skip
	return doc.insert().name


def enter_marks(session, offering, rows):
	"""rows: {student: (cia, ese) or "AB"}"""
	return frappe.get_doc(
		{
			"doctype": "Mark Sheet Entry", "exam_session": session, "course_offering": offering,
			"marks": [
				{"student": s, "absent": 1} if v == "AB" else {"student": s, "cia": v[0], "ese": v[1]}
				for s, v in rows.items()
			],
		}
	).insert().name  # fmt: skip


class ExamFixture(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		clear_world()
		make_company(COLLEGE, "EXTC")
		for year in ("2022", "2026"):
			make_year(year)
		make_program(PROGRAM, COLLEGE)
		for user, role in (
			(COE_USER, "COE"), (FACULTY, "Instructor"), (OTHER_FACULTY, "Instructor"),
			(STUDENT_22_USER, "Student"), (STUDENT_26_USER, "Student"), (GUARDIAN_USER, "Guardian"),
		):  # fmt: skip
			make_login(user, role)
		regs = {}
		for code, year in (("R2022", "2022"), ("R2026", "2026")):
			regs[code] = make_regulation(f"{code}-EXM", COLLEGE, [PROGRAM], year).name
			seed_regulation(regs[code], code)
		cls.pre_term = make_term(PRE_TERM, "2022-06-01", "2022-09-30")
		cls.term = make_term(TERM, "2022-10-01", "2023-02-28")
		cls.s22 = make_student("Exm22", COLLEGE, "2022")
		cls.s26 = make_student("Exm26", COLLEGE, "2026")
		cls.s_ab = make_student("ExmAb", COLLEGE, "2022")
		cls.s_sa = make_student("ExmSa", COLLEGE, "2022")
		for student in (cls.s22, cls.s26, cls.s_ab, cls.s_sa):
			enroll(student, PROGRAM, "2022", submit=True)
		assert frappe.db.get_value("Student", cls.s26.name, "oc_regulation") == regs["R2026"]
		for student, user in ((cls.s22, STUDENT_22_USER), (cls.s26, STUDENT_26_USER)):
			frappe.db.set_value("Student", student.name, "user", user)
		make_guardian("Examguardian", [cls.s22.name], user=GUARDIAN_USER)
		cls.instructor, cls.other_instructor = make_instructor(FACULTY), make_instructor(OTHER_FACULTY)
		for course in (*COURSES, PRE_COURSE[0]):
			make_course(course)
		cls.curriculum22 = make_curriculum(regs["R2022"], {**COURSES, PRE_COURSE[0]: PRE_COURSE[1]})
		cls.curriculum26 = make_curriculum(regs["R2026"], COURSES)
		cls.session = frappe.get_doc(
			{"doctype": "Exam Session", "company": COLLEGE, "academic_term": cls.term, "status": "Marks Entry"}
		).insert()
		cls.pre_session = frappe.get_doc(
			{"doctype": "Exam Session", "company": COLLEGE, "academic_term": cls.pre_term, "status": "Marks Entry"}
		).insert()
		cls.offerings22, cls.offerings26 = {}, {}
		cls.pre_offering = make_offering(PRE_COURSE[0], cls.curriculum22, cls.pre_term, [cls.s22.name])
		enter_marks(cls.pre_session.name, cls.pre_offering, {cls.s22.name: (36, 54)})
		for course in COURSES:
			cls.offerings22[course] = make_offering(
				course, cls.curriculum22, cls.term, [cls.s22.name, cls.s_ab.name, cls.s_sa.name],
				cls.instructor if course == "EXM TH" else None,
			)  # fmt: skip
			cls.offerings26[course] = make_offering(course, cls.curriculum26, cls.term, [cls.s26.name])
			ab = {cls.s_ab.name: "AB" if course == "EXM TH" else MARKS[course]}
			enter_marks(cls.session.name, cls.offerings22[course], {cls.s22.name: MARKS[course], **ab})
			enter_marks(cls.session.name, cls.offerings26[course], {cls.s26.name: MARKS[course]})

	def setUp(self):
		frappe.db.savepoint("exam_test")  # each test starts from the class fixture
		self.addCleanup(frappe.db.rollback, save_point="exam_test")
		self.addCleanup(frappe.set_user, "Administrator")
		patcher = patch.object(
			results, "eligibility_status", lambda student, term: "Shortage" if student == self.s_sa.name else "Eligible"
		)
		patcher.start()
		self.addCleanup(patcher.stop)

	def run_session(self):
		results.compute_student_result(self.s22.name, self.pre_session.name)
		return {
			s.name: results.compute_student_result(s.name, self.session.name)
			for s in (self.s22, self.s26, self.s_ab, self.s_sa)
		}

	def result(self, student, session=None):
		return frappe.get_doc("Student Result", f"SR-{(session or self.session).name}-{student.name}")

	def publish(self, publish_at):
		frappe.db.set_value("Exam Session", self.session.name, {"status": "Published", "publish_at": publish_at})


class TestResultRun(ExamFixture):
	def grades(self, doc):
		return {c.course: (c.grade, c.grade_point, c.result) for c in doc.courses}

	def test_same_marks_get_the_regulation_correct_grades(self):
		self.run_session()
		before, after = self.grades(self.result(self.s22)), self.grades(self.result(self.s26))
		self.assertEqual(before["EXM TH"], ("B+", 7, "Pass"))  # 63 under R2022
		self.assertEqual(after["EXM TH"], ("B", 6.5, "Pass"))  # 63 under R2026
		for grades in (before, after):
			self.assertEqual(grades["EXM LB"], ("A", 8, "Pass"))  # 75
			self.assertEqual(grades["EXM TL"], ("A+", 9, "Pass"))  # 85 on a 50:50 course
			self.assertEqual(grades["EXM FA"], ("U", 0, "Fail"))  # ESE 44%, total 60%

	def test_sgpa_and_cgpa_match_the_hand_calculation(self):
		self.run_session()
		r22, r26 = self.result(self.s22), self.result(self.s26)
		self.assertEqual(self.result(self.s22, self.pre_session).sgpa, 9.0)  # 4 credits at A+
		self.assertEqual(r22.sgpa, 8.11)  # (3*7 + 2*8 + 4*9) / 9
		self.assertEqual(r22.cgpa, 8.38)  # (36 + 73) / 13: the earlier session counts
		self.assertEqual(r22.credits_earned, 9)
		self.assertEqual((r26.sgpa, r26.cgpa), (7.94, 7.94))  # (3*6.5 + 2*8 + 4*9) / 9, no earlier session

	def test_shortage_and_absent_codes(self):
		self.run_session()
		sa, ab = self.result(self.s_sa), self.result(self.s_ab)
		self.assertEqual({c.result for c in sa.courses}, {"SA"})
		self.assertEqual({c.grade for c in sa.courses}, {"SA"})
		self.assertEqual((sa.sgpa, sa.credits_earned), (0, 0))
		self.assertEqual(self.grades(ab)["EXM TH"], ("AB", 0, "AB"))
		self.assertEqual(self.grades(ab)["EXM LB"], ("A", 8, "Pass"))
		self.assertEqual(ab.sgpa, 8.67)  # (2*8 + 4*9) / 6: AB and the failed course are outside the credits

	def test_rerun_replaces_the_result_and_a_published_session_is_refused(self):
		names = self.run_session()
		entry = frappe.get_doc("Mark Sheet Entry", {"course_offering": self.offerings22["EXM FA"]})
		row = next(r for r in entry.marks if r.student == self.s22.name)
		row.ese = 40  # 33.6 + 40 = 73.6 and ESE 66.7%: now passes
		entry.save()
		self.assertEqual(results.compute_student_result(self.s22.name, self.session.name), names[self.s22.name])
		self.assertEqual(frappe.db.count("Student Result", {"student": self.s22.name, "exam_session": self.session.name}), 1)
		doc = self.result(self.s22)
		self.assertEqual(len(doc.courses), 4)
		self.assertEqual(self.grades(doc)["EXM FA"], ("A", 8, "Pass"))
		self.publish(add_days(now_datetime(), -1))
		with self.assertRaises(frappe.ValidationError):
			results.compute_student_result(self.s22.name, self.session.name)
		frappe.set_user(COE_USER)
		with self.assertRaises(frappe.ValidationError):
			api.run_results(self.session.name, PROGRAM)

	def test_run_results_queues_one_item_per_enrolled_student_and_needs_the_coe_role(self):
		frappe.set_user(FACULTY)
		with self.assertRaises(frappe.PermissionError):
			api.run_results(self.session.name, PROGRAM)
		frappe.set_user(COE_USER)
		with patch.object(bulk, "enqueue_run") as enqueue:
			name = api.run_results(self.session.name, PROGRAM)
		enqueue.assert_called_once_with(name)
		run = frappe.get_doc("Bulk Run", name)
		self.assertEqual(sorted(frappe.parse_json(run.items)), sorted([self.s22.name, self.s26.name, self.s_ab.name, self.s_sa.name]))
		self.assertEqual(run.handler, results.HANDLER)
		self.assertEqual(run.get_parameters(), {"exam_session": self.session.name})

	def test_missing_marks_stop_the_student_instead_of_guessing(self):
		frappe.db.delete("Mark Sheet Entry Row", {"parent": frappe.db.get_value("Mark Sheet Entry", {"course_offering": self.offerings26["EXM TH"]}), "student": self.s26.name})
		with self.assertRaises(frappe.ValidationError):
			results.compute_student_result(self.s26.name, self.session.name)


class TestResultAccess(ExamFixture):
	def visible(self, user):
		frappe.set_user(user)
		return sorted(frappe.get_list("Student Result", pluck="student"))

	def test_nothing_is_readable_before_publication(self):
		self.run_session()
		self.assertEqual(self.visible(STUDENT_22_USER), [])
		self.assertEqual(self.visible(GUARDIAN_USER), [])
		self.assertFalse(frappe.has_permission("Student Result", "read", self.result(self.s22), user=STUDENT_22_USER))
		self.publish(add_days(now_datetime(), 1))  # published, but publish_at is still ahead
		self.assertEqual(self.visible(STUDENT_22_USER), [])
		self.assertFalse(frappe.has_permission("Student Result", "read", self.result(self.s22), user=STUDENT_22_USER))

	def test_students_and_guardians_read_only_their_own_after_publication(self):
		self.run_session()
		self.publish(add_days(now_datetime(), -1))
		own22, own26 = self.result(self.s22), self.result(self.s26)
		pre = self.result(self.s22, self.pre_session)  # an unpublished session stays hidden
		self.assertEqual(self.visible(STUDENT_22_USER), [self.s22.name])
		self.assertEqual(self.visible(STUDENT_26_USER), [self.s26.name])
		self.assertEqual(self.visible(GUARDIAN_USER), [self.s22.name])
		self.assertTrue(frappe.has_permission("Student Result", "read", own22, user=STUDENT_22_USER))
		self.assertTrue(frappe.has_permission("Student Result", "read", own22, user=GUARDIAN_USER))
		self.assertFalse(frappe.has_permission("Student Result", "read", own26, user=STUDENT_22_USER))
		self.assertFalse(frappe.has_permission("Student Result", "read", own26, user=GUARDIAN_USER))
		self.assertFalse(frappe.has_permission("Student Result", "read", pre, user=STUDENT_22_USER))
		self.assertFalse(frappe.has_permission("Student Result", "write", own22, user=STUDENT_22_USER))

	def test_staff_read_regardless_of_publication(self):
		self.run_session()
		self.assertEqual(len(self.visible(COE_USER)), 5)  # four results of the session and the earlier one

	def test_staff_roles_may_print_results(self):
		for role in ("System Manager", "COE", "Dean Academics", "Academics User"):
			perm = frappe.get_all("DocPerm", {"parent": "Student Result", "role": role}, ["print"])
			self.assertEqual([p.print for p in perm], [1], role)

	def test_grade_sheet_carries_a_verifiable_qr(self):
		self.run_session()
		frappe.set_user(COE_USER)
		with self.assertRaises(frappe.ValidationError):
			api.issue_grade_sheet(self.result(self.s22).name)  # not published yet
		self.publish(add_days(now_datetime(), 1))
		with self.assertRaises(frappe.ValidationError):
			api.issue_grade_sheet(self.result(self.s22).name)  # published, but publish_at is still ahead
		self.publish(add_days(now_datetime(), -1))
		code = frappe.db.get_value("Verifiable Document", api.issue_grade_sheet(self.result(self.s22).name), "code")
		html = frappe.get_print("Student Result", self.result(self.s22).name, "Grade Sheet")
		self.assertIn(code, html)
		self.assertIn("B+", html)
		self.assertEqual(verify(code)["holder_name"], self.s22.student_name)


class TestMarkSheetEntry(ExamFixture):
	def entry(self):
		return frappe.get_doc("Mark Sheet Entry", {"course_offering": self.offerings22["EXM TH"]})

	def test_only_the_offerings_instructors_and_coe_may_edit(self):
		entry = self.entry()
		for user, allowed in ((FACULTY, True), (COE_USER, True), (OTHER_FACULTY, False)):
			self.assertEqual(frappe.has_permission("Mark Sheet Entry", "write", entry, user=user), allowed, user)
		frappe.set_user(OTHER_FACULTY)
		self.assertEqual(frappe.get_list("Mark Sheet Entry", pluck="name"), [])
		frappe.set_user(FACULTY)
		self.assertEqual(frappe.get_list("Mark Sheet Entry", pluck="name"), [entry.name])

	def test_faculty_edit_while_marks_entry_and_not_after(self):
		frappe.set_user(FACULTY)
		entry = self.entry()
		entry.marks[0].cia = 30
		entry.save()
		frappe.set_user("Administrator")
		self.publish(add_days(now_datetime(), -1))
		entry.reload()
		entry.marks[0].cia = 31
		with self.assertRaises(frappe.ValidationError):
			entry.save()

	def test_marks_beyond_the_maximum_are_rejected_and_absent_zeroes_marks(self):
		entry = self.entry()
		entry.marks[0].cia = 41  # Theory CIA maximum is 40
		with self.assertRaises(frappe.ValidationError):
			entry.save()
		entry.reload()
		entry.marks[0].absent, entry.marks[0].cia, entry.marks[0].ese = 1, 12, 20
		entry.save()
		self.assertEqual((entry.marks[0].cia, entry.marks[0].ese), (0, 0))


class TestSchemeValidation(ExamFixture):
	def setUp(self):
		super().setUp()
		frappe.db.set_value("Regulation", "R2022-EXM-EXTC", "status", "Draft")  # an Effective one locks its scheme

	def test_grading_scheme_rejects_overlapping_ranges(self):
		scheme = frappe.get_doc("Grading Scheme", "R2022-EXM-EXTC")
		scheme.grades[1].min_mark = 85
		scheme.grades[2].max_mark = 86
		with self.assertRaises(frappe.ValidationError):
			scheme.save()

	def test_grading_scheme_requires_the_result_codes(self):
		scheme = frappe.get_doc("Grading Scheme", "R2022-EXM-EXTC")
		scheme.codes = [c for c in scheme.codes if c.code != "SA"]
		with self.assertRaises(frappe.ValidationError):
			scheme.save()
