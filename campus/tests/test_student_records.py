"""M06-01, M05-03 integration tests: Exam Withdrawal Application (once per programme, window, Principal's special
case, HOD -> Principal approval, WD/WC on the Student Result), Break of Study (limits, approval, academic status)
and the guard of the exam hooks on unmigrated sites. Rejoin: test_rejoin."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from campus.campus_platform.approvals import approve, request_approval
from campus.examinations import registration, results
from campus.student_services import student_records_setup
from campus.student_services import lifecycle
from campus.student_services.lifecycle import LOG
from campus.student_services.api import pending_bridge_courses, withdrawal_code
from campus.tests.approval_fixtures import make_department
from campus.tests.factories import make_user
from campus.tests.test_results import COLLEGE, PROGRAM, ExamFixture, make_course

CLERK, HOD_USER, PRINCIPAL_USER = "rec-clerk@example.com", "rec-hod@example.com", "rec-principal@example.com"
WITHDRAWAL, BREAK, REJOIN = "Exam Withdrawal Application", "Break of Study", "Rejoin Application"
# course -> days before today of its exam: EXM TH was 11 days ago, past the 10-day window
EXAM_DAYS_AGO = {"EXM TH": 11, "EXM LB": 3, "EXM TL": 2, "EXM FA": 1}
BRIDGE_COURSE = "EXM BRIDGE"


def hold(position, user, scope):
	frappe.get_doc(
		{"doctype": "Position Holder", "position": position, "scope_value": scope, "user": user, "from_date": add_days(today(), -30)}
	).insert()  # fmt: skip


def clear_records():
	for doctype, child in ((WITHDRAWAL, "Exam Withdrawal Course"), (REJOIN, "Rejoin Bridge Course"), (BREAK, None)):
		names = frappe.get_all(doctype, {"company": COLLEGE}, pluck="name") or [""]
		frappe.db.delete("Approval Request", {"reference_doctype": doctype, "reference_name": ["in", names]})
		if child:
			frappe.db.delete(child, {"parent": ["in", names]})
		frappe.db.delete(doctype, {"name": ["in", names]})
	frappe.db.delete("Position Holder", {"user": ["in", [HOD_USER, PRINCIPAL_USER]]})


class StudentRecordsFixture(ExamFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		clear_records()
		student_records_setup.seed_policies()
		cls.department = make_department("Exm Records CSE", COLLEGE)
		frappe.db.set_value("Program", PROGRAM, "department", cls.department)
		for user in (CLERK, HOD_USER, PRINCIPAL_USER):
			make_user(user, [COLLEGE])
		hold("HOD", HOD_USER, cls.department)
		hold("PRINCIPAL", PRINCIPAL_USER, COLLEGE)
		session = frappe.get_doc("Exam Session", cls.session.name)
		session.update(
			{
				"registration_opens": add_days(today(), -40), "registration_closes": add_days(today(), -30),
				"exam_start": add_days(today(), -11), "exam_end": add_days(today(), 5),
				"schedule": [{"course": c, "exam_date": add_days(today(), -d), "slot": "FN"} for c, d in EXAM_DAYS_AGO.items()],
			}
		)  # fmt: skip
		session.save()
		for student, offerings in ((cls.s22, cls.offerings22), (cls.s26, cls.offerings26)):
			frappe.get_doc(
				{
					"doctype": "Exam Registration", "exam_session": cls.session.name, "student": student.name, "program": PROGRAM,
					"courses": [{"course": c, "course_offering": o, "kind": "Current"} for c, o in offerings.items()],
				}
			).insert()  # fmt: skip

	def approve_fully(self, doc, requester=CLERK):
		frappe.set_user(requester)
		request = request_approval(doc.doctype, doc.name)
		frappe.set_user(HOD_USER)
		approve(request)
		frappe.set_user(PRINCIPAL_USER)
		approve(request)
		frappe.set_user("Administrator")
		return frappe.get_doc(doc.doctype, doc.name)

	def withdrawal(self, student, courses, user=CLERK, **extra):
		frappe.set_user(user)
		doc = frappe.get_doc(
			{
				"doctype": WITHDRAWAL, "student": student.name, "exam_session": self.session.name,
				"reason": "Hospitalised", "courses": [{"course": c} for c in courses], **extra,
			}
		).insert()  # fmt: skip
		frappe.set_user("Administrator")
		return doc

	def study_break(self, student, from_date, to_date, **extra):
		frappe.set_user(CLERK)
		doc = frappe.get_doc(
			{"doctype": BREAK, "student": student.name, "from_date": from_date, "to_date": to_date, "reason": "Illness", **extra}
		).insert()
		frappe.set_user("Administrator")
		return doc


class TestExamWithdrawal(StudentRecordsFixture):
	def grades(self, student):
		doc = frappe.get_doc("Student Result", f"SR-{self.session.name}-{student.name}")
		return doc, {c.course: (c.grade, c.grade_point, c.result) for c in doc.courses}

	def test_withdrawal_takes_the_regulation_code_and_the_window_from_the_records(self):
		r22, r26 = self.withdrawal(self.s22, ["EXM LB"]), self.withdrawal(self.s26, ["EXM LB"])
		self.assertEqual((r22.withdrawal_code, r26.withdrawal_code), ("WD", "WC"))
		self.assertEqual(r22.window_days, 10)
		self.assertEqual(r22.courses[0].exam_date, frappe.utils.getdate(add_days(today(), -3)))
		self.assertEqual((r22.program, r22.department, r22.company), (PROGRAM, self.department, COLLEGE))

	def test_approval_runs_hod_then_principal_and_codes_the_results(self):
		self.run_session()
		doc = self.approve_fully(self.withdrawal(self.s22, ["EXM LB"]))
		self.assertEqual(doc.docstatus, 1)
		request = frappe.get_doc("Approval Request", {"reference_doctype": WITHDRAWAL, "reference_name": doc.name})
		self.assertEqual([(a.action, a.approver) for a in request.actions if a.level], [("Approve", HOD_USER), ("Approve", PRINCIPAL_USER)])
		result, grades = self.grades(self.s22)
		self.assertEqual(grades["EXM LB"], ("WD", 0, "WD"))
		self.assertEqual(grades["EXM TH"], ("B+", 7, "Pass"))
		self.assertEqual(result.sgpa, 8.14)  # (3*7 + 4*9) / 7: the withdrawn course is outside the credits
		self.approve_fully(self.withdrawal(self.s26, ["EXM TL"]))
		self.assertEqual(self.grades(self.s26)[1]["EXM TL"], ("WC", 0, "WD"))

	def test_cancelling_a_withdrawal_regrades_the_course(self):
		self.run_session()
		doc = self.approve_fully(self.withdrawal(self.s22, ["EXM LB"]))
		doc.cancel()
		self.assertEqual(self.grades(self.s22)[1]["EXM LB"], ("A", 8, "Pass"))

	def test_a_second_withdrawal_in_the_programme_is_refused(self):
		self.approve_fully(self.withdrawal(self.s22, ["EXM LB"]))
		with self.assertRaisesRegex(frappe.ValidationError, "once"):
			self.withdrawal(self.s22, ["EXM TL"])

	def test_a_second_approved_draft_cannot_submit(self):
		first, second = self.withdrawal(self.s22, ["EXM LB"]), self.withdrawal(self.s22, ["EXM TL"])
		self.approve_fully(first)
		with self.assertRaisesRegex(frappe.ValidationError, "once"):
			self.approve_fully(second)

	def test_eleven_days_after_the_exam_is_refused_without_the_special_case(self):
		doc = self.withdrawal(self.s22, ["EXM TH"])
		frappe.set_user(CLERK)
		with self.assertRaisesRegex(frappe.ValidationError, "within 10 days"):
			request_approval(WITHDRAWAL, doc.name)

	def test_the_principal_special_case_lifts_the_window(self):
		doc = self.withdrawal(self.s22, ["EXM TH"])
		frappe.set_user(PRINCIPAL_USER)
		doc.reload()
		doc.update({"special_case": 1, "special_case_reason": "Accident on the exam day, records attached"})
		doc.save()
		self.assertEqual(doc.special_case_by, PRINCIPAL_USER)
		self.assertEqual(self.approve_fully(doc).docstatus, 1)

	def test_only_the_principal_may_grant_the_special_case(self):
		with self.assertRaises(frappe.PermissionError):
			self.withdrawal(self.s22, ["EXM TH"], special_case=1, special_case_reason="Please")
		frappe.set_user(PRINCIPAL_USER)
		doc = frappe.get_doc({"doctype": WITHDRAWAL, "student": self.s22.name, "exam_session": self.session.name,
			"reason": "Ill", "courses": [{"course": "EXM TH"}], "special_case": 1})  # fmt: skip
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			doc.insert()

	def test_the_window_is_the_exam_rule_set_value(self):
		regulation = frappe.db.get_value("Student", self.s22.name, "oc_regulation")
		frappe.db.set_value("Exam Rule Set", {"regulation": regulation}, "oc_withdrawal_days", 15)
		doc = self.withdrawal(self.s22, ["EXM TH"])
		self.assertEqual(self.approve_fully(doc).docstatus, 1)

	def test_the_requester_never_approves(self):
		doc = self.withdrawal(self.s22, ["EXM LB"], user=HOD_USER)
		frappe.set_user(HOD_USER)
		with self.assertRaisesRegex(frappe.ValidationError, "cannot approve"):
			request_approval(WITHDRAWAL, doc.name)

	def test_a_course_must_be_registered_and_scheduled(self):
		frappe.db.delete("Exam Schedule", {"parent": self.session.name, "course": "EXM FA"})
		with self.assertRaisesRegex(frappe.ValidationError, "not scheduled"):
			self.withdrawal(self.s22, ["EXM FA"])
		make_course(BRIDGE_COURSE)
		with self.assertRaisesRegex(frappe.ValidationError, "not registered"):
			self.withdrawal(self.s22, [BRIDGE_COURSE])

	def test_a_withdrawal_is_only_for_courses_of_the_term(self):
		doc = frappe.get_doc("Exam Registration", {"exam_session": self.session.name, "student": self.s22.name})
		doc.append("courses", {"course": "EXM PRE", "kind": "Arrear"})
		doc.save()
		with self.assertRaisesRegex(frappe.ValidationError, "course of the term"):
			self.withdrawal(self.s22, ["EXM PRE"])

	def test_the_window_is_checked_again_at_final_approval(self):
		doc = self.withdrawal(self.s22, ["EXM LB"])  # 3 days after the exam
		frappe.set_user(CLERK)
		request = request_approval(WITHDRAWAL, doc.name)
		frappe.set_user(HOD_USER)
		approve(request)
		regulation = frappe.db.get_value("Student", self.s22.name, "oc_regulation")
		frappe.db.set_value("Exam Rule Set", {"regulation": regulation}, "oc_withdrawal_days", 1)
		frappe.set_user(PRINCIPAL_USER)
		with self.assertRaisesRegex(frappe.ValidationError, "within 1 days"):
			approve(request)

	def test_a_programme_without_a_department_is_refused(self):
		frappe.db.set_value("Program", PROGRAM, "department", None)
		with self.assertRaisesRegex(frappe.ValidationError, "department"):
			self.withdrawal(self.s22, ["EXM LB"])

	def test_without_an_approval_policy_nothing_submits(self):
		frappe.db.delete("Approval Policy", {"document_type": WITHDRAWAL})
		doc = self.withdrawal(self.s22, ["EXM LB"])
		frappe.set_user(CLERK)
		with self.assertRaisesRegex(frappe.ValidationError, "Approval Policy"):
			request_approval(WITHDRAWAL, doc.name)
		self.assertEqual(frappe.db.get_value(WITHDRAWAL, doc.name, "docstatus"), 0)


class TestBreakOfStudy(StudentRecordsFixture):
	def status(self, student):
		return frappe.db.get_value("Student", student.name, "oc_academic_status")

	def test_an_approved_break_puts_the_student_on_break(self):
		doc = self.approve_fully(self.study_break(self.s22, "2025-06-01", "2026-05-31"))
		self.assertEqual((doc.docstatus, doc.break_days), (1, 365))
		self.assertEqual(self.status(self.s22), "On Break")
		log = frappe.get_last_doc(LOG, {"student": self.s22.name}, order_by="creation desc, name desc")
		self.assertEqual(
			(log.from_status, log.to_status, log.effective_date, log.source_doctype, log.source_name, log.approved_by),
			("Active", "On Break", getdate("2025-06-01"), BREAK, doc.name, PRINCIPAL_USER),
		)
		doc.cancel()
		self.assertEqual(self.status(self.s22), "Active")

	def test_more_than_a_year_needs_the_exceptional_year_with_a_reason(self):
		with self.assertRaisesRegex(frappe.ValidationError, "1 year"):
			self.study_break(self.s22, "2025-06-01", "2026-08-31")
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			self.study_break(self.s22, "2025-06-01", "2026-08-31", exceptional=1)
		with self.assertRaisesRegex(frappe.ValidationError, "2 year"):
			self.study_break(self.s22, "2025-06-01", "2027-07-31", exceptional=1, exceptional_reason="Surgery")
		doc = self.study_break(self.s22, "2025-06-01", "2026-08-31", exceptional=1, exceptional_reason="Surgery")
		self.assertEqual(self.approve_fully(doc).docstatus, 1)

	def test_earlier_breaks_count_and_a_student_on_break_cannot_take_another(self):
		self.approve_fully(self.study_break(self.s22, "2024-06-01", "2024-12-31"))
		with self.assertRaisesRegex(frappe.ValidationError, "on a break"):
			self.study_break(self.s22, "2025-06-01", "2025-07-31")
		frappe.db.set_value("Student", self.s22.name, "oc_academic_status", "Active")  # as if rejoined
		with self.assertRaisesRegex(frappe.ValidationError, "1 year"):
			self.study_break(self.s22, "2025-06-01", "2025-12-31")  # 214 + 214 days

	def test_overlapping_breaks_are_refused(self):
		self.approve_fully(self.study_break(self.s22, "2024-06-01", "2024-12-31"))
		frappe.db.set_value("Student", self.s22.name, "oc_academic_status", "Active")  # as if rejoined
		with self.assertRaisesRegex(frappe.ValidationError, "overlaps"):
			self.study_break(self.s22, "2024-10-01", "2024-11-30")

	def test_cancelling_restores_the_previous_status_through_a_reversal(self):
		doc = self.approve_fully(self.study_break(self.s22, "2025-06-01", "2025-12-31"))
		self.assertEqual((doc.previous_status, self.status(self.s22)), ("Active", "On Break"))
		doc.cancel()
		self.assertEqual(self.status(self.s22), "Active")
		log = frappe.get_last_doc(LOG, {"student": self.s22.name}, order_by="creation desc, name desc")
		self.assertEqual((log.kind, log.from_status, log.to_status, log.source_name), ("Reversal", "On Break", "Active", doc.name))

	def pre_l01_break(self, previous):
		"""A break approved before L-01 as the patch finds it (old academic statuses, no lifecycle record), migrated."""
		doc = self.approve_fully(self.study_break(self.s22, "2025-06-01", "2025-12-31"))
		frappe.db.delete(LOG, {"student": self.s22.name})
		frappe.db.set_value("Student", self.s22.name, "oc_academic_status", "Break of Study")
		frappe.db.set_value(BREAK, doc.name, "previous_status", previous)
		self.assertEqual(lifecycle.migrate_student(self.s22.name), "On Break")
		return doc

	def test_cancelling_a_migrated_break_restores_the_mapped_previous_status(self):
		doc = self.pre_l01_break("Long Absent")
		migrated = frappe.get_last_doc(LOG, {"student": self.s22.name})
		self.assertEqual((migrated.kind, migrated.source_name), ("Migrated", doc.name))
		frappe.get_doc(BREAK, doc.name).cancel()
		self.assertEqual(self.status(self.s22), "Active")
		log = frappe.get_last_doc(LOG, {"student": self.s22.name}, order_by="creation desc, name desc")
		self.assertEqual((log.kind, log.from_status, log.to_status, log.reverses), ("Reversal", "On Break", "Active", migrated.name))

	def test_a_detained_student_on_a_migrated_break_keeps_the_detention(self):
		doc = self.pre_l01_break("Detained")
		lifecycle.migrate_break_statuses()
		self.assertEqual(frappe.db.get_value(BREAK, doc.name, "previous_status"), "Active")
		self.assertEqual(frappe.db.get_value("Student", self.s22.name, "oc_detained"), 1)
		frappe.get_doc(BREAK, doc.name).cancel()
		self.assertEqual(self.status(self.s22), "Active")

	def test_a_break_cannot_start_unless_the_table_permits_it(self):
		frappe.db.set_value("Student", self.s22.name, "oc_academic_status", "Withdrawn")
		doc = self.study_break(self.s22, "2025-06-01", "2025-12-31")
		with self.assertRaisesRegex(frappe.ValidationError, "cannot move from Withdrawn to On Break"):
			self.approve_fully(doc)
		self.assertEqual(self.status(self.s22), "Withdrawn")

	def test_a_student_without_a_programme_is_refused(self):
		frappe.db.delete("Program Enrollment", {"student": self.s22.name})
		with self.assertRaisesRegex(frappe.ValidationError, "programme"):
			self.study_break(self.s22, "2025-06-01", "2025-12-31")

	def test_without_an_approval_policy_nothing_submits(self):
		frappe.db.delete("Approval Policy", {"document_type": BREAK})
		doc = self.study_break(self.s22, "2025-06-01", "2025-12-31")
		frappe.set_user(CLERK)
		with self.assertRaisesRegex(frappe.ValidationError, "Approval Policy"):
			request_approval(BREAK, doc.name)
		self.assertEqual(self.status(self.s22), "Active")

	def test_students_on_break_are_skipped_by_registration_and_the_result_run(self):
		self.assertIn(self.s22.name, results.program_students(self.session, PROGRAM))
		self.approve_fully(self.study_break(self.s22, "2025-06-01", "2025-12-31"))
		before = frappe.get_doc("Exam Registration", {"exam_session": self.session.name, "student": self.s22.name}).modified
		self.assertIsNone(registration.register(self.s22.name, self.session.name))
		after = frappe.get_doc("Exam Registration", {"exam_session": self.session.name, "student": self.s22.name}).modified
		self.assertEqual(before, after)
		students = results.program_students(self.session, PROGRAM)
		self.assertNotIn(self.s22.name, students)
		self.assertIn(self.s26.name, students)

	def test_a_result_refresh_skips_a_student_on_break(self):
		self.run_session()
		self.approve_fully(self.withdrawal(self.s22, ["EXM LB"]))
		frappe.db.set_value("Student", self.s22.name, "oc_academic_status", "On Break")
		name = f"SR-{self.session.name}-{self.s22.name}"
		before = frappe.db.get_value("Student Result", name, "modified")
		frappe.get_doc(WITHDRAWAL, {"student": self.s22.name, "docstatus": 1}).cancel()
		self.assertEqual(frappe.db.get_value("Student Result", name, "modified"), before)


class TestUnmigratedSite(StudentRecordsFixture):
	"""The shared tree runs on sites that have not synced these DocTypes yet: the exam hooks must be no-ops."""

	def test_hooks_are_no_ops_without_the_tables(self):
		self.approve_fully(self.withdrawal(self.s22, ["EXM LB"]))
		self.assertEqual(withdrawal_code(self.s22.name, self.session.name, "EXM LB"), "WD")
		with patch.object(frappe.db, "table_exists", return_value=False):
			self.assertIsNone(withdrawal_code(self.s22.name, self.session.name, "EXM LB"))
			self.assertEqual(pending_bridge_courses(self.s22.name), [])
