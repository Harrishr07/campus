"""M06-01 integration tests: Exam Session schedule, bulk Exam Registration, eligibility, exam fee, dues gating, portal."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, now_datetime, today

from campus.campus_finance.api import raise_fee_invoice
from campus.campus_platform import bulk
from campus.examinations import api, exam_fee, registration
from campus.examinations.seed import seed_regulation
from campus.student_services import portal
from campus.student_services.api import attendance_snapshot
from campus.tests.broadcast_fixtures import make_guardian
from campus.tests.finance_factories import make_finance_company
from campus.tests.test_attendance_condonation import inline_bulk
from campus.tests.test_regulation import enroll, make_program, make_regulation, make_student, make_year, year_name
from campus.tests.test_results import make_login, make_term
from campus.tests.utils import CampusTestCase

COLLEGE = "Exam Reg Test College"
PROGRAM = "Exam Reg Test BE"
PRE_TERM, TERM = "Exr Pre", "Exr Odd"
COE_USER, FACULTY = "exr-coe@example.com", "exr-faculty@example.com"
OK_USER, SA_USER, DROP_USER, GUARDIAN_USER = (
	"exr-ok@example.com", "exr-sa@example.com", "exr-drop@example.com", "exr-guardian@example.com",
)  # fmt: skip
# course -> exam type; all semester 1 of one curriculum. EXR IO has no end-semester exam.
COURSES = {"EXR A": "Theory", "EXR B": "Theory", "EXR D": "Theory", "EXR IO": "Internal Only", "EXR OLD": "Theory"}
FEE_PER_COURSE = 300
SLABS = [(1, 7, 100), (8, 15, 250)]


def clear_world():
	students = frappe.get_all("Student", {"oc_company": COLLEGE}, pluck="name") or [""]
	registrations = frappe.get_all("Exam Registration", {"company": COLLEGE}, pluck="name") or [""]
	frappe.db.delete("Exam Registration Course", {"parent": ["in", registrations]})
	frappe.db.delete("Exam Registration", {"name": ["in", registrations]})
	frappe.db.delete("Exam Late Fee Slab", {"parent": ["in", frappe.get_all("Exam Fee Rate", {"company": COLLEGE}, pluck="name") or [""]]})
	frappe.db.delete("Exam Fee Rate", {"company": COLLEGE})
	results = frappe.get_all("Student Result", {"student": ["in", students]}, pluck="name") or [""]
	frappe.db.delete("Student Result Course", {"parent": ["in", results]})
	frappe.db.delete("Student Result", {"name": ["in", results]})
	sessions = frappe.get_all("Exam Session", {"company": COLLEGE}, pluck="name") or [""]
	frappe.db.delete("Exam Schedule", {"parent": ["in", sessions]})
	frappe.db.delete("Exam Session", {"name": ["in", sessions]})
	runs = frappe.get_all("Attendance Eligibility Run", {"company": COLLEGE}, pluck="name") or [""]
	frappe.db.delete("Attendance Eligibility Row", {"parent": ["in", runs]})
	frappe.db.delete("Attendance Eligibility Run", {"name": ["in", runs]})
	registrations = frappe.get_all("Course Registration", {"student": ["in", students]}, pluck="name") or [""]
	frappe.db.delete("Course Registration Item", {"parent": ["in", registrations]})
	frappe.db.delete("Course Registration", {"name": ["in", registrations]})
	groups = frappe.get_all("Student Group", {"oc_company": COLLEGE}, pluck="name") or [""]
	frappe.db.delete("Student Group Student", {"parent": ["in", groups]})
	frappe.db.delete("Student Group", {"name": ["in", groups]})
	frappe.db.delete("Student Guardian", {"parent": ["in", students]})
	frappe.db.delete("Guardian", {"guardian_name": "Exrguardian"})
	frappe.db.delete("Program Enrollment", {"student": ["in", students]})
	frappe.db.delete("Student", {"name": ["in", students]})
	for name in frappe.get_all("Curriculum", {"program": PROGRAM}, pluck="name"):
		frappe.db.delete("Curriculum Course", {"parent": name})
		frappe.db.delete("Curriculum", {"name": name})


def make_curriculum(regulation):
	for course in COURSES:
		if not frappe.db.exists("Course", course):
			frappe.get_doc({"doctype": "Course", "course_name": course, "oc_company": COLLEGE}).insert()
	rows = [
		{"semester": 1, "course": course, "category": "PCC", "exam_type": kind, "credits_override": 1, "credits": 3}
		for course, kind in COURSES.items()
	]  # fmt: skip
	return frappe.get_doc(
		{"doctype": "Curriculum", "program": PROGRAM, "regulation": regulation, "status": "Draft", "courses": rows}
	).insert().name  # fmt: skip


def make_offering(course, curriculum, term, students):
	return frappe.get_doc(
		{
			"doctype": "Student Group", "student_group_name": f"{course}-{term}", "group_based_on": "Course",
			"academic_year": year_name("2022"), "academic_term": term, "program": PROGRAM, "course": course,
			"oc_company": COLLEGE, "oc_curriculum": curriculum, "oc_semester": 1,
			"students": [{"student": s} for s in students],
		}
	).insert().name  # fmt: skip


def submitted_course_registration(student, term, items):
	"""A submitted Course Registration row as P1-T13 leaves it; only its items are read here, so its own
	rule checks and enrollment side effects (tested in test_registration) are bypassed."""
	doc = frappe.get_doc(
		{
			"doctype": "Course Registration", "name": f"CREG-EXR-{student}", "student": student, "academic_term": term,
			"semester": 1, "company": COLLEGE, "docstatus": 1,
			"items": [{"course": c, "registration_type": t, "semester": 1} for c, t in items],
		}
	)  # fmt: skip
	doc.db_insert()
	for row in doc.items:
		row.db_insert()


def published_result(session, student, outcomes):
	frappe.get_doc(
		{
			"doctype": "Student Result", "student": student, "exam_session": session, "company": COLLEGE, "program": PROGRAM,
			"courses": [{"course": c, "credits": 3, "result": r, "grade": "U" if r == "Fail" else r} for c, r in outcomes],
		}
	).insert()  # fmt: skip


def locked_snapshot(term, statuses):
	return frappe.get_doc(
		{
			"doctype": "Attendance Eligibility Run", "company": COLLEGE, "academic_term": term, "locked": 1,
			"rows": [{"student": s, "status": status} for s, status in statuses.items()],
		}
	).insert()


def with_customer(student):
	customer = frappe.get_doc({"doctype": "Customer", "customer_name": f"{student} Customer", "customer_type": "Individual"}).insert()
	frappe.db.set_value("Student", student, "customer", customer.name)


class ExamRegistrationFixture(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		clear_world()
		make_finance_company(COLLEGE, "EXRT")
		make_year("2022")
		make_program(PROGRAM, COLLEGE)
		for user, role in (
			(COE_USER, "COE"), (FACULTY, "Instructor"), (OK_USER, "Student"), (SA_USER, "Student"),
			(DROP_USER, "Student"), (GUARDIAN_USER, "Guardian"),
		):  # fmt: skip
			make_login(user, role)
		regulation = make_regulation("R2022-EXR", COLLEGE, [PROGRAM], "2022").name
		seed_regulation(regulation, "R2022")
		cls.pre_term = make_term(PRE_TERM, "2022-06-01", "2022-09-30")
		cls.term = make_term(TERM, "2022-10-01", "2023-02-28")
		names = ("Exrok", "Exrsa", "Exrdrop", "Exrdues", "Exrold")
		students = {n: make_student(n, COLLEGE, "2022") for n in names}
		for student in students.values():
			enroll(student, PROGRAM, "2022", submit=True)
			with_customer(student.name)
		cls.ok, cls.sa, cls.drop, cls.dues, cls.old = (students[n].name for n in names)
		for student, user in ((cls.ok, OK_USER), (cls.sa, SA_USER), (cls.drop, DROP_USER)):
			frappe.db.set_value("Student", student, "user", user)
		make_guardian("Exrguardian", [cls.drop], user=GUARDIAN_USER)
		curriculum = make_curriculum(regulation)
		current = [cls.ok, cls.sa, cls.drop, cls.dues]
		cls.offerings = {c: make_offering(c, curriculum, cls.term, current) for c in ("EXR A", "EXR B", "EXR IO")}
		cls.offerings["EXR D"] = make_offering("EXR D", curriculum, cls.term, [cls.drop])
		make_offering("EXR OLD", curriculum, cls.pre_term, [cls.ok, cls.sa, cls.old])
		submitted_course_registration(cls.drop, cls.term, [("EXR A", "Regular"), ("EXR B", "Regular"), ("EXR D", "Dropped")])
		pre_session = frappe.get_doc(
			{"doctype": "Exam Session", "company": COLLEGE, "academic_term": cls.pre_term, "status": "Draft"}
		).insert()
		published_result(pre_session.name, cls.ok, [("EXR OLD", "Pass")])
		published_result(pre_session.name, cls.sa, [("EXR OLD", "Fail")])  # an arrear (U)
		published_result(pre_session.name, cls.old, [("EXR OLD", "AB")])  # arrear only: no course this term
		frappe.db.set_value(
			"Exam Session", pre_session.name, {"status": "Published", "publish_at": add_days(now_datetime(), -30)}
		)
		cls.snapshot = locked_snapshot(
			cls.term, {cls.ok: "Eligible", cls.sa: "Detained (SA)", cls.drop: "Eligible", cls.dues: "Eligible"}
		)
		cls.session = frappe.get_doc(
			{
				"doctype": "Exam Session", "company": COLLEGE, "academic_term": cls.term, "status": "Draft",
				"registration_opens": add_days(today(), -20), "registration_closes": add_days(today(), 5),
				"exam_start": add_days(today(), 20), "exam_end": add_days(today(), 30),
				"schedule": [
					{"course": "EXR A", "exam_date": add_days(today(), 20), "slot": "FN"},
					{"course": "EXR B", "exam_date": add_days(today(), 22), "slot": "AN"},
				],
			}
		).insert()  # fmt: skip
		frappe.get_doc(
			{
				"doctype": "Exam Fee Rate", "company": COLLEGE, "fee_per_course": FEE_PER_COURSE,
				"late_fee_slabs": [{"from_day": a, "to_day": b, "late_fee": fee} for a, b, fee in SLABS],
			}
		).insert()  # fmt: skip

	def setUp(self):
		frappe.db.savepoint("exr_test")
		self.addCleanup(frappe.db.rollback, save_point="exr_test")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.form_dict.clear)

	def register_all(self):
		with patch.object(registration, "run_bulk", inline_bulk):
			registration.start(self.session.name)

	def reg(self, student):
		return frappe.get_doc("Exam Registration", registration.registration_name(self.session.name, student))

	def courses(self, student):
		return {r.course: (r.kind, r.eligibility) for r in self.reg(student).courses}

	def set_closes(self, days_from_today):
		frappe.db.set_value("Exam Session", self.session.name, "registration_closes", add_days(today(), days_from_today))

	def confirm_as(self, user, student):
		frappe.set_user(user)
		frappe.form_dict.clear()
		with patch("frappe.enqueue"):
			return portal.confirm_exam_registration(registration.registration_name(self.session.name, student), student)


class TestExamSession(ExamRegistrationFixture):
	def test_schedule_rows_are_one_per_course_inside_the_exam_dates(self):
		doc = frappe.get_doc("Exam Session", self.session.name)
		doc.append("schedule", {"course": "EXR A", "exam_date": add_days(today(), 21), "slot": "AN"})
		with self.assertRaisesRegex(frappe.ValidationError, "EXR A"):
			doc.save()
		doc.reload()
		doc.schedule[0].exam_date = add_days(today(), 31)
		with self.assertRaisesRegex(frappe.ValidationError, "exam dates"):
			doc.save()

	def test_registration_dates_must_be_in_order(self):
		doc = frappe.get_doc("Exam Session", self.session.name)
		doc.registration_closes = add_days(today(), -21)
		with self.assertRaisesRegex(frappe.ValidationError, "Registration"):
			doc.save()


class TestBulkRegistration(ExamRegistrationFixture):
	def test_start_queues_term_students_and_arrear_students_and_needs_the_coe(self):
		frappe.set_user(FACULTY)
		with self.assertRaises(frappe.PermissionError):
			api.start_registration(self.session.name)
		frappe.set_user(COE_USER)
		with patch.object(bulk, "enqueue_run") as enqueue:
			name = api.start_registration(self.session.name)
		enqueue.assert_called_once_with(name)
		run = frappe.get_doc("Bulk Run", name)
		self.assertEqual(frappe.parse_json(run.items), sorted([self.ok, self.sa, self.drop, self.dues, self.old]))
		self.assertEqual((run.handler, run.get_parameters()), (registration.HANDLER, {"exam_session": self.session.name}))
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[api.start_registration], ["POST"])

	def test_courses_are_current_dropped_and_arrears_with_their_eligibility(self):
		self.register_all()
		eligible, sa = "Eligible", "Not eligible (SA)"
		self.assertEqual(self.courses(self.ok), {"EXR A": ("Current", eligible), "EXR B": ("Current", eligible)})
		# R2022 cl. 15.1: the SA student's term courses are barred, the arrear stays registrable
		self.assertEqual(
			self.courses(self.sa),
			{"EXR A": ("Current", sa), "EXR B": ("Current", sa), "EXR OLD": ("Arrear", eligible)},
		)
		self.assertEqual(
			self.courses(self.drop),
			{"EXR A": ("Current", eligible), "EXR B": ("Current", eligible), "EXR D": ("Dropped", eligible)},
		)
		self.assertEqual(self.courses(self.old), {"EXR OLD": ("Arrear", eligible)})  # AB is an arrear too
		self.assertEqual(self.reg(self.sa).attendance_status, "Shortage")
		self.assertEqual(frappe.db.count("Exam Registration", {"exam_session": self.session.name}), 5)

	def test_rerun_adds_only_missing_courses(self):
		self.register_all()
		before = {r.course: r.name for r in self.reg(self.ok).courses}
		self.register_all()
		self.assertEqual({r.course: r.name for r in self.reg(self.ok).courses}, before)
		self.assertEqual(frappe.db.count("Exam Registration", {"exam_session": self.session.name}), 5)
		group = frappe.get_doc("Student Group", self.offerings["EXR D"])
		group.append("students", {"student": self.ok})
		group.save()
		self.register_all()
		after = {r.course: r.name for r in self.reg(self.ok).courses}
		self.assertEqual(set(after), {"EXR A", "EXR B", "EXR D"})
		self.assertEqual({c: after[c] for c in before}, before)  # existing rows kept, one row added
		self.assertEqual(frappe.db.count("Exam Registration Course", {"parent": self.reg(self.ok).name}), 3)

	def test_a_term_student_missing_from_the_locked_snapshot_fails_instead_of_passing(self):
		frappe.db.delete("Attendance Eligibility Row", {"parent": self.snapshot.name, "student": self.dues})
		with self.assertRaisesRegex(frappe.ValidationError, "attendance eligibility"):
			registration.register(self.dues, self.session.name)

	def test_a_published_session_takes_no_registration(self):
		frappe.db.set_value("Exam Session", self.session.name, {"status": "Published", "publish_at": now_datetime()})
		with self.assertRaises(frappe.ValidationError):
			registration.register(self.ok, self.session.name)

	def test_detention_and_debarment_flags(self):
		self.register_all()
		doc = self.reg(self.ok)
		doc.detained = 1
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			doc.save()
		doc = self.reg(self.ok)
		doc.detained, doc.detention_reason = 1, "Disciplinary committee order"
		doc.save()
		self.assertEqual({r.eligibility for r in doc.courses}, {"Not eligible (Detained)"})
		doc = self.reg(self.sa)
		doc.debarred, doc.debarment_reason = 1, "Malpractice in the previous session"
		doc.save()
		self.assertEqual({r.eligibility for r in doc.courses}, {"Not eligible (Debarred)"})  # the arrear too


class TestAttendanceSnapshot(ExamRegistrationFixture):
	def test_only_a_locked_run_counts_and_an_approved_condonation_makes_a_medical_band_eligible(self):
		self.assertEqual(attendance_snapshot(self.ok, self.term, COLLEGE), "Eligible")
		self.assertEqual(attendance_snapshot(self.sa, self.term, COLLEGE), "Shortage")
		self.assertIsNone(attendance_snapshot(self.old, self.term, COLLEGE))
		frappe.db.set_value("Attendance Eligibility Row", {"parent": self.snapshot.name, "student": self.ok}, "status", "Condonation")
		self.assertEqual(attendance_snapshot(self.ok, self.term, COLLEGE), "Shortage")
		frappe.get_doc(
			{"doctype": "Condonation Request", "name": "CND-EXR-1", "student": self.ok, "academic_term": self.term, "docstatus": 1}
		).db_insert()  # an approved request, as the approval engine leaves it
		self.assertEqual(attendance_snapshot(self.ok, self.term, COLLEGE), "Eligible")
		frappe.db.set_value("Attendance Eligibility Run", self.snapshot.name, "locked", 0)
		self.assertIsNone(attendance_snapshot(self.ok, self.term, COLLEGE))


class TestExamFee(ExamRegistrationFixture):
	def test_confirmation_raises_one_exam_fee_invoice_in_a_worker(self):
		self.register_all()
		frappe.set_user(DROP_USER)
		frappe.form_dict.clear()
		name = registration.registration_name(self.session.name, self.drop)
		web = (frappe.session.user, frappe.session.sid)
		with patch("frappe.set_user", side_effect=AssertionError("set_user in a request path")), patch(
			"frappe.enqueue"
		) as enqueue:
			portal.confirm_exam_registration(name, self.drop)
		self.assertEqual((frappe.session.user, frappe.session.sid), web)
		queued = [c for c in enqueue.call_args_list if c.args and c.args[0] == exam_fee.JOB]
		self.assertEqual([c.kwargs["registration"] for c in queued], [name])
		self.assertTrue(queued[0].kwargs["enqueue_after_commit"])
		frappe.set_user("Administrator")
		doc = self.reg(self.drop)
		# 3 eligible courses x 300, on time
		self.assertEqual((doc.confirmed, doc.late_days, doc.exam_fee, doc.late_fee, doc.fee_total), (1, 0, 900, 0, 900))
		self.assertFalse(doc.fee_invoice)
		exam_fee.raise_fee(name)
		exam_fee.raise_fee(name)  # idempotent
		doc.reload()
		invoice = frappe.get_doc("Sales Invoice", doc.fee_invoice)
		self.assertEqual(
			(invoice.docstatus, invoice.grand_total, invoice.items[0].item_code, invoice.student, invoice.company),
			(1, 900, "Exam", self.drop, COLLEGE),
		)
		self.assertEqual(frappe.db.count("Sales Invoice", {"student": self.drop, "docstatus": 1}), 1)

	def test_the_sa_student_pays_for_the_arrear_only(self):
		self.register_all()
		self.confirm_as(SA_USER, self.sa)
		doc = self.reg(self.sa)
		self.assertEqual((doc.exam_fee, doc.fee_total), (300, 300))  # EXR OLD only

	def test_late_registration_applies_the_slab_of_the_days_late(self):
		self.register_all()
		self.set_closes(-10)  # 10 days late: slab 8-15, 250
		self.confirm_as(OK_USER, self.ok)
		doc = self.reg(self.ok)
		self.assertEqual((doc.late_days, doc.exam_fee, doc.late_fee, doc.fee_total), (10, 600, 250, 850))
		frappe.set_user("Administrator")
		self.set_closes(-3)  # 3 days late: slab 1-7, 100
		self.confirm_as(DROP_USER, self.drop)
		doc = self.reg(self.drop)
		self.assertEqual((doc.late_days, doc.late_fee, doc.fee_total), (3, 100, 1000))
		frappe.set_user("Administrator")
		self.set_closes(-16)  # past the last slab: closed
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			self.confirm_as(SA_USER, self.sa)
		frappe.set_user("Administrator")
		self.assertFalse(self.reg(self.sa).confirmed)

	def test_no_fee_rate_refuses_confirmation(self):
		self.register_all()
		frappe.db.delete("Exam Fee Rate", {"company": COLLEGE})
		with self.assertRaisesRegex(frappe.ValidationError, "Exam Fee Rate"):
			self.confirm_as(OK_USER, self.ok)

	def test_fee_rate_slabs_must_not_overlap_and_one_rate_per_company_and_program(self):
		doc = frappe.get_doc(
			{
				"doctype": "Exam Fee Rate", "company": COLLEGE, "program": PROGRAM, "fee_per_course": 100,
				"late_fee_slabs": [{"from_day": 1, "to_day": 7, "late_fee": 50}, {"from_day": 7, "to_day": 10, "late_fee": 80}],
			}
		)  # fmt: skip
		with self.assertRaisesRegex(frappe.ValidationError, "overlap"):
			doc.insert()
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			frappe.get_doc({"doctype": "Exam Fee Rate", "company": COLLEGE, "fee_per_course": 100}).insert()

	def test_a_program_rate_beats_the_company_rate(self):
		frappe.get_doc({"doctype": "Exam Fee Rate", "company": COLLEGE, "program": PROGRAM, "fee_per_course": 450}).insert()
		self.register_all()
		self.confirm_as(OK_USER, self.ok)
		self.assertEqual(self.reg(self.ok).exam_fee, 900)  # 2 x 450


class TestDuesGating(ExamRegistrationFixture):
	def test_exam_dues_block_hall_tickets_not_registration(self):
		raise_fee_invoice(self.dues, "Exam", 500, COLLEGE, "Previous session exam fee")
		raise_fee_invoice(self.ok, "Tuition", 1000, COLLEGE, "Tuition")
		self.register_all()
		self.assertEqual(len(self.reg(self.dues).courses), 2)  # registered despite the exam dues
		with patch("frappe.enqueue"):
			registration.confirm(self.reg(self.dues).name)
		exam_fee.raise_fee(self.reg(self.dues).name)
		block = api.exam_dues_block(self.dues, self.session.name)
		self.assertEqual((block.blocked, block.amount), (True, 1100))  # 500 earlier + 2 x 300 this session
		block = api.exam_dues_block(self.ok, self.session.name)
		self.assertEqual((block.blocked, block.amount), (False, 0))  # tuition dues are not the Exam scope


class TestPortal(ExamRegistrationFixture):
	def test_confirm_is_post_only_and_only_for_the_student_themself(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[portal.confirm_exam_registration], ["POST"])
		self.register_all()
		with self.assertRaises(frappe.PermissionError):
			self.confirm_as(OK_USER, self.drop)  # another student
		with self.assertRaises(frappe.PermissionError):
			self.confirm_as(GUARDIAN_USER, self.drop)  # a guardian sees it but the student confirms
		frappe.set_user(OK_USER)
		with self.assertRaises(frappe.PermissionError):  # a registration id of another student under one's own id
			with patch("frappe.enqueue"):
				portal.confirm_exam_registration(registration.registration_name(self.session.name, self.drop), self.ok)
		self.confirm_as(DROP_USER, self.drop)
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			self.confirm_as(DROP_USER, self.drop)

	def test_student_and_guardian_see_the_registration_on_the_dashboard(self):
		from campus.www.campus_portal import index

		self.register_all()
		for user in (DROP_USER, GUARDIAN_USER):
			frappe.set_user(user)
			frappe.form_dict.clear()
			context = frappe._dict()
			index.get_context(context)
			(row,) = context.exam_registrations
			self.assertEqual(row["exam_session"], self.session.name)
			self.assertEqual([c["course"] for c in row["courses"]], ["EXR A", "EXR B", "EXR D"])
			self.assertEqual(row["can_confirm"], user == DROP_USER)
		frappe.set_user(SA_USER)
		(row,) = portal.my_exam_registrations(self.sa)["registrations"]
		self.assertEqual({c["course"]: c["eligibility"] for c in row["courses"]}["EXR A"], "Not eligible (SA)")
