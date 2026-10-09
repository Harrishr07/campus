"""M06-05, M06-06 integration tests of result processing (P2-T19): Mark Moderation through the approval engine,
grace marks with the Grace Mark Audit, CIA carried forward for arrears, versioned results, Passing Board
publication, the release permission (API and portal), the release notice and classification inputs.

Expected values are hand-computed in the comments. Fixture world: campus.tests.test_results.ExamFixture
(R2022 student s22 and R2026 student s26 with the same raw marks; s_ab absent from EXM TH; s_sa short of
attendance). R2022 / R2026 theory: CIA 40 + ESE 60, ESE >= 45 %, total >= 50 %.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, get_datetime, now_datetime, today

from campus.campus_platform.approvals import approve, request_approval
from campus.examinations import api, publication, results, seed
from campus.examinations.report.grace_mark_audit.grace_mark_audit import execute as grace_report
from campus.student_services import portal
from campus.tests.approval_fixtures import level
from campus.tests.test_results import (
	COE_USER,
	COLLEGE,
	FACULTY,
	GUARDIAN_USER,
	PRE_COURSE,
	PROGRAM,
	STUDENT_22_USER,
	ExamFixture,
	enter_marks,
	make_login,
	make_offering,
)

APPROVER = "exam-principal@example.com"
ACADEMICS_USER, DEAN_USER = "exam-academics@example.com", "exam-dean@example.com"
MODERATION, RATIFICATION = "Mark Moderation", "Result Ratification"
PRE = PRE_COURSE[0]


class ResultFixture(ExamFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for user, role in ((APPROVER, "Principal"), (ACADEMICS_USER, "Academics User"), (DEAN_USER, "Dean Academics")):
			make_login(user, role)

	def setUp(self):
		super().setUp()
		for doctype, policy in ((MODERATION, "Result Test Moderation"), (RATIFICATION, "Result Test Ratification")):
			frappe.db.delete("Approval Policy", {"document_type": doctype})
			frappe.get_doc(
				{"doctype": "Approval Policy", "policy_name": policy, "document_type": doctype,
				"levels": [level("User", APPROVER, title="Principal")]}
			).insert()  # fmt: skip

	def latest(self, student, session=None):
		name = frappe.db.get_value(
			"Student Result", {"student": student.name, "exam_session": (session or self.session).name, "is_latest": 1}
		)
		return frappe.get_doc("Student Result", name)

	def row(self, student, course, session=None):
		return next(c for c in self.latest(student, session).courses if c.course == course)

	def moderate(self, course, adjustment, approve_it=True):
		frappe.set_user(COE_USER)
		doc = frappe.get_doc(
			{"doctype": MODERATION, "exam_session": self.session.name, "course": course, "adjustment": adjustment,
			"justification": "Paper set above the syllabus level"}
		).insert()  # fmt: skip
		request = request_approval(MODERATION, doc.name)
		if approve_it:
			frappe.set_user(APPROVER)
			approve(request)
		frappe.set_user("Administrator")
		return doc.reload()

	def allow_grace(self, student, per_course=5, courses=2, total=6):
		regulation = frappe.db.get_value("Student", student.name, "oc_regulation")
		values = {"grace_allowed": 1, "grace_max_per_course": per_course, "grace_max_courses": courses, "grace_max_total": total}
		frappe.db.set_value("Exam Rule Set", {"regulation": regulation}, values)  # the rule records lock once Effective
		return frappe.db.get_value("Exam Rule Set", {"regulation": regulation})

	def set_ese(self, student, course, ese, session=None):
		sheets = frappe.get_all("Mark Sheet Entry", {"exam_session": (session or self.session).name, "course": course}, pluck="name")
		frappe.db.set_value("Mark Sheet Entry Row", {"parent": ["in", sheets], "student": student.name}, "ese", ese)


class TestMarkModeration(ResultFixture):
	def test_an_approved_moderation_lifts_the_ese_of_the_course(self):
		self.moderate("EXM FA", 1)
		self.run_session()
		fa22, fa26 = self.row(self.s22, "EXM FA"), self.row(self.s26, "EXM FA")
		# ESE 26.4 + 1 = 27.4 of 60 (45.7 %), total 61
		self.assertEqual((fa22.moderation, fa22.ese, fa22.total, fa22.grade, fa22.result), (1, 27.4, 61, "B+", "Pass"))
		self.assertEqual((fa26.grade, fa26.grade_point, fa26.result), ("B", 6.5, "Pass"))  # R2026 61-65
		self.assertEqual(self.row(self.s22, "EXM TH").moderation, 0)  # other courses untouched

	def test_a_moderation_awaiting_approval_changes_nothing(self):
		self.moderate("EXM FA", 1, approve_it=False)
		self.run_session()
		self.assertEqual(self.row(self.s22, "EXM FA").result, "Fail")

	def test_the_requester_cannot_approve_and_a_direct_submit_is_refused(self):
		doc = self.moderate("EXM FA", 1, approve_it=False)
		request = frappe.db.get_value("Approval Request", {"reference_doctype": MODERATION, "reference_name": doc.name})
		frappe.set_user(COE_USER)
		with self.assertRaises(frappe.PermissionError):
			approve(request)
		frappe.set_user("Administrator")
		doc.reload()
		with self.assertRaises(frappe.ValidationError):
			doc.submit()

	def test_justification_is_required_and_one_per_course(self):
		frappe.set_user(COE_USER)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": MODERATION, "exam_session": self.session.name, "course": "EXM FA", "adjustment": 1, "justification": " "}).insert()
		frappe.set_user("Administrator")
		self.moderate("EXM FA", 1, approve_it=False)
		with self.assertRaises(frappe.ValidationError):
			self.moderate("EXM FA", 2, approve_it=False)

	def test_no_moderation_after_publication(self):
		self.publish(add_days(now_datetime(), -1))
		with self.assertRaises(frappe.ValidationError):
			self.moderate("EXM FA", 1, approve_it=False)


class TestGrace(ResultFixture):
	def test_grace_passes_a_near_miss_and_is_audited_with_the_rule(self):
		rule = self.allow_grace(self.s22)
		self.run_session()
		fa = self.row(self.s22, "EXM FA")
		# ESE 26.4 needs 0.6 for 45 %: one whole grace mark, ESE 27.4, total 61 -> B+
		self.assertEqual((fa.grace, fa.grace_rule, fa.ese, fa.grade, fa.result), (1, rule, 27.4, "B+", "Pass"))
		self.assertEqual(self.row(self.s26, "EXM FA").result, "Fail")  # R2026 rule set has no grace
		_columns, rows = grace_report({"company": COLLEGE, "exam_session": self.session.name})
		audited = [(r["student"], r["course"], r["grace"], r["grace_rule"]) for r in rows]
		self.assertIn((self.s22.name, "EXM FA", 1, rule), audited)
		self.assertNotIn(self.s26.name, [r["student"] for r in rows])
		self.assertEqual(next(r for r in rows if r["student"] == self.s22.name)["rule_limits"], "5 / 2 / 6")

	def test_no_grace_beyond_the_per_course_limit(self):
		self.allow_grace(self.s22, per_course=0.5, courses=2, total=6)
		self.run_session()
		self.assertEqual((self.row(self.s22, "EXM FA").grace, self.row(self.s22, "EXM FA").result), (0, "Fail"))
		self.assertEqual(grace_report({"company": COLLEGE})[1], [])

	def test_grace_is_off_unless_the_rule_allows_it(self):
		self.run_session()
		self.assertEqual(self.row(self.s22, "EXM FA").result, "Fail")


class TestArrears(ResultFixture):
	def setUp(self):
		super().setUp()
		# s22 fails EXM PRE in the earlier session: CIA 12 + ESE 20 = 32
		frappe.db.set_value("Mark Sheet Entry Row", {"parent": frappe.db.get_value("Mark Sheet Entry", {"course_offering": self.pre_offering}), "student": self.s22.name}, {"cia": 12, "ese": 20})
		results.compute_student_result(self.s22.name, self.pre_session.name)
		frappe.db.set_value("Exam Session", self.pre_session.name, {"status": "Published", "publish_at": add_days(now_datetime(), -60)})
		# EXM PRE is offered again this term (to s_ab); s22 writes it as an arrear on the same sheet
		offering = make_offering(PRE, self.curriculum22, self.term, [self.s_ab.name])
		frappe.get_doc(
			{"doctype": "Exam Registration", "exam_session": self.session.name, "student": self.s22.name, "program": PROGRAM,
			"courses": [{"course": PRE, "kind": "Arrear"}]}
		).insert()  # fmt: skip
		enter_marks(self.session.name, offering, {self.s_ab.name: (30, 40), self.s22.name: (39, 40)})

	def test_r2022_carries_the_first_attempts_cia_forward(self):
		self.run_session()
		pre = self.row(self.s22, PRE)
		# CIA 12 (first attempt, not the 39 on the new sheet) + ESE 40 = 52 -> C 5
		self.assertEqual((pre.kind, pre.attempt, pre.cia, pre.ese, pre.total, pre.grade, pre.result), ("Arrear", 2, 12, 40, 52, "C", "Pass"))
		self.assertEqual(pre.credits, 4)  # from the curriculum row of the first attempt's offering
		doc = self.latest(self.s22)
		self.assertEqual((doc.arrear_count, doc.result), (1, "Reappear"))  # EXM PRE cleared, EXM FA failed
		self.assertEqual(doc.sgpa, 8.11)  # the arrear stays outside this session's SGPA
		self.assertEqual(doc.cgpa, 7.15)  # passes only: TH 3*7 + LB 2*8 + TL 4*9 + PRE 4*5 = 93 over 13 credits

	def test_without_carry_forward_the_new_cia_counts(self):
		regulation = frappe.db.get_value("Student", self.s22.name, "oc_regulation")
		frappe.db.set_value("Exam Rule Set", {"regulation": regulation}, "cia_carry_forward", 0)
		self.run_session()
		pre = self.row(self.s22, PRE)
		self.assertEqual((pre.cia, pre.total, pre.grade), (39, 79, "A"))  # 39 + 40 = 79 -> A

	def test_an_arrear_without_a_mark_sheet_stays_pending_and_the_rest_is_graded(self):
		frappe.db.delete("Mark Sheet Entry Row", {"student": self.s22.name, "parent": frappe.db.get_value("Mark Sheet Entry", {"exam_session": self.session.name, "course": PRE})})
		self.run_session()
		pre = self.row(self.s22, PRE)
		self.assertEqual((pre.kind, pre.result, pre.grade_point), ("Arrear", "Pending", 0))
		doc = self.latest(self.s22)
		self.assertEqual(self.row(self.s22, "EXM TH").grade, "B+")  # current courses graded as usual
		self.assertEqual((doc.sgpa, doc.arrear_count, doc.result), (8.11, 2, "Reappear"))  # EXM PRE still owed, EXM FA failed

	def test_an_arrear_row_needs_a_registration_on_the_sheet(self):
		sheet = frappe.get_doc("Mark Sheet Entry", {"course_offering": self.offerings22["EXM TH"]})
		sheet.append("marks", {"student": self.s26.name, "cia": 20, "ese": 30})  # s26 is neither a member nor registered
		with self.assertRaises(frappe.ValidationError):
			sheet.save()


class TestVersions(ResultFixture):
	def test_before_publication_a_rerun_replaces_the_draft(self):
		first = self.run_session()[self.s22.name]
		self.set_ese(self.s22, "EXM FA", 40)
		second = results.compute_student_result(self.s22.name, self.session.name)
		self.assertEqual(second, first)
		self.assertEqual(frappe.db.count("Student Result", {"student": self.s22.name, "exam_session": self.session.name}), 1)
		self.assertEqual((self.latest(self.s22).version, self.row(self.s22, "EXM FA").grade), (1, "A"))

	def ratify(self, user=COE_USER, approver=APPROVER):
		frappe.set_user(user)
		doc = frappe.get_doc({"doctype": RATIFICATION, "exam_session": self.session.name, "reason": "Revaluation outcomes"}).insert()
		request = request_approval(RATIFICATION, doc.name)
		frappe.set_user(approver)
		try:
			approve(request)
		finally:
			frappe.set_user("Administrator")
		return doc.reload()

	def test_after_publication_a_rerun_makes_a_pending_version_until_ratified(self):
		first = self.run_session()[self.s22.name]
		self.publish(add_days(now_datetime(), -1))
		self.set_ese(self.s22, "EXM FA", 40)  # e.g. a revaluation: 33.6 + 40 = 73.6 -> A
		second = results.compute_student_result(self.s22.name, self.session.name)
		self.assertNotEqual(second, first)
		new, old = frappe.get_doc("Student Result", second), frappe.get_doc("Student Result", first)
		self.assertEqual((new.version, new.is_latest, new.pending_ratification, new.previous_version), (2, 0, 1, first))
		self.assertEqual((old.version, old.is_latest), (1, 1))  # the published version stays the one everyone sees
		self.assertEqual([c.grade for c in old.courses if c.course == "EXM FA"], ["U"])
		self.assertIn("EXM FA: U (Fail) -> A (Pass), total 60 -> 73.6", new.change_log)
		self.assertIn("SGPA: 8.11 -> 8.08", new.change_log)  # (21 + 16 + 36 + 3*8) / 12 = 8.08
		self.assertIn("Arrears: 1 -> 0", new.change_log)
		# a re-run with the same marks keeps the one pending version
		self.assertEqual(results.compute_student_result(self.s22.name, self.session.name), second)
		self.assertEqual(frappe.db.count("Student Result", {"student": self.s22.name, "exam_session": self.session.name}), 2)
		for user in (STUDENT_22_USER, GUARDIAN_USER, ACADEMICS_USER):
			frappe.set_user(user)
			self.assertEqual(frappe.get_list("Student Result", {"student": self.s22.name, "exam_session": self.session.name}, pluck="name"), [first], user)
			self.assertFalse(frappe.has_permission("Student Result", "read", new, user=user))
		frappe.set_user("Administrator")
		self.assertTrue(frappe.has_permission("Student Result", "read", new, user=COE_USER))
		# ratified: the new version is the latest, the old one stays readable to the COE, the student is told
		with patch("campus.examinations.doctype.result_ratification.result_ratification.send") as send:
			ratification = self.ratify()
		self.assertEqual([i.student_result for i in ratification.items], [second])
		new.reload(), old.reload()
		self.assertEqual((new.is_latest, new.pending_ratification, old.is_latest), (1, 0, 0))
		self.assertEqual(send.call_args.args[2][0], f"Student:{self.s22.name}")
		frappe.set_user(STUDENT_22_USER)
		self.assertEqual(frappe.get_list("Student Result", {"exam_session": self.session.name}, pluck="name"), [second])
		frappe.set_user("Administrator")
		self.assertTrue(frappe.has_permission("Student Result", "read", old, user=COE_USER))

	def test_a_rerun_back_to_the_published_marks_drops_the_pending_version(self):
		first = self.run_session()[self.s22.name]
		self.publish(add_days(now_datetime(), -1))
		self.set_ese(self.s22, "EXM FA", 40)
		results.compute_student_result(self.s22.name, self.session.name)
		self.set_ese(self.s22, "EXM FA", 26.4)
		self.assertEqual(results.compute_student_result(self.s22.name, self.session.name), first)
		self.assertEqual(frappe.db.count("Student Result", {"student": self.s22.name, "exam_session": self.session.name}), 1)

	def test_a_withdrawal_refresh_after_publication_is_pending_too(self):
		first = self.run_session()[self.s22.name]
		self.publish(add_days(now_datetime(), -1))
		with patch.object(results, "withdrawal_code", lambda student, session, course: "WD" if course == "EXM FA" else None):
			api.refresh_student_result(self.s22.name, self.session.name)
		self.assertEqual(self.latest(self.s22).name, first)
		pending = frappe.get_all("Student Result", {"student": self.s22.name, "pending_ratification": 1}, pluck="name")
		self.assertEqual(len(pending), 1)

	def test_ratification_needs_a_pending_version_and_another_approver(self):
		self.run_session()
		self.publish(add_days(now_datetime(), -1))
		with self.assertRaises(frappe.ValidationError):
			self.ratify()  # nothing pending
		self.set_ese(self.s22, "EXM FA", 40)
		results.compute_student_result(self.s22.name, self.session.name)
		with self.assertRaises(frappe.PermissionError):
			self.ratify(approver=COE_USER)  # the requester never approves

	def test_the_run_button_path_is_open_after_publication(self):
		self.run_session()
		self.publish(add_days(now_datetime(), -1))
		frappe.set_user(COE_USER)
		with patch("campus.campus_platform.bulk.enqueue_run"):
			self.assertTrue(results.start_run(self.session.name, PROGRAM))


class TestReleasePermission(ResultFixture):
	def visible(self, user):
		frappe.set_user(user)
		try:
			return sorted(frappe.get_list("Student Result", {"exam_session": self.session.name}, pluck="student"))
		finally:
			frappe.set_user("Administrator")

	def test_before_publication_only_coe_system_manager_and_dean_academics_read(self):
		self.run_session()
		everyone = sorted([self.s22.name, self.s26.name, self.s_ab.name, self.s_sa.name])
		self.assertEqual(self.visible(COE_USER), everyone)
		self.assertEqual(self.visible(DEAN_USER), everyone)
		self.assertEqual(self.visible(ACADEMICS_USER), [])  # before publication the ESE stays with the COE
		self.assertFalse(frappe.has_permission("Student Result", "read", self.latest(self.s22), user=ACADEMICS_USER))
		self.assertFalse(frappe.has_permission("Student Result", "read", self.latest(self.s22), user=FACULTY))  # no role right
		self.publish(add_days(now_datetime(), 1))  # published, release still ahead
		self.assertEqual(self.visible(ACADEMICS_USER), [])
		self.assertEqual(self.visible(STUDENT_22_USER), [])
		self.publish(add_days(now_datetime(), -1))
		self.assertEqual(self.visible(ACADEMICS_USER), everyone)  # the normal staff scope after release
		self.assertTrue(frappe.has_permission("Student Result", "read", self.latest(self.s22), user=ACADEMICS_USER))
		self.assertEqual(self.visible(STUDENT_22_USER), [self.s22.name])

	def test_the_portal_shows_nothing_before_release(self):
		self.run_session()
		self.publish(add_days(now_datetime(), 1))
		for user in (STUDENT_22_USER, GUARDIAN_USER):
			frappe.set_user(user)
			self.assertEqual([r["exam_session"] for r in portal.get_results()["results"]], [], user)
		frappe.set_user("Administrator")
		self.publish(add_days(now_datetime(), -1))
		frappe.set_user(STUDENT_22_USER)
		self.assertEqual([r["exam_session"] for r in portal.get_results()["results"]], [self.session.name])


class PassingBoardFixture(ResultFixture):
	def setUp(self):
		super().setUp()
		from campus.academic_governance.seed import seed_body_types

		seed_body_types()
		self.member = frappe.db.get_value("Instructor", self.instructor, "employee")

	def complete_run(self, session=None, program=PROGRAM, status="Completed", finished_days=-2):
		"""A finished Result Run of the programme (the tests compute results directly, as its handler does)."""
		return frappe.get_doc(
			{"doctype": "Bulk Run", "run_type": results.RUN_TYPE, "status": status, "handler": results.HANDLER, "items": "[]",
			"total": 0, "parameters": frappe.as_json({"exam_session": (session or self.session).name, "program": program}),
			"finished_at": add_days(now_datetime(), finished_days) if status == "Completed" else None}
		).insert(ignore_permissions=True).name  # fmt: skip

	def meeting(self, body_type="Passing Board", decision="Approved", session=None, held=True, days=-1):
		body = frappe.get_doc(
			{"doctype": "Body", "body_name": f"{body_type} {frappe.generate_hash(length=5)}", "company": COLLEGE, "body_type": body_type,
			"members": [{"category": "Internal", "employee": self.member, "from_date": add_days(today(), -400)}]}
		).insert()  # fmt: skip
		meeting = frappe.get_doc({"doctype": "Body Meeting", "body": body.name, "meeting_date": add_days(today(), days), "venue": "COE Office"}).insert()
		for row in meeting.attendance:
			row.present = 1
		meeting.save()
		bound = self.session.name if session is None else session
		meeting.append("resolutions", {"resolution_text": f"Results of {bound} approved", "decision": decision, "exam_session": bound or None})
		meeting.status = "Held" if held else meeting.status
		meeting.save()
		return meeting.name, meeting.resolutions[0].resolution_no

	def publish_with_board(self, release_at, user=COE_USER, **meeting):
		meeting, resolution = self.meeting(**meeting)
		frappe.set_user(user)
		try:
			return publication.publish_results(self.session.name, release_at, meeting, resolution)
		finally:
			frappe.set_user("Administrator")

	def ready(self):
		names = self.run_session()
		self.complete_run()
		return names


class TestPublication(PassingBoardFixture):
	def test_a_passing_board_resolution_publishes_at_the_release_time(self):
		self.ready()
		release = add_days(now_datetime(), 1).replace(hour=10, minute=0, second=0, microsecond=0)
		self.publish_with_board(release)
		session = frappe.get_doc("Exam Session", self.session.name)
		self.assertEqual((session.status, get_datetime(session.publish_at)), ("Published", release))
		self.assertTrue(session.passing_board_meeting and session.passing_board_resolution)

	def test_other_bodies_and_other_decisions_are_refused(self):
		self.ready()
		with self.assertRaisesRegex(frappe.ValidationError, "Passing Board"):
			self.publish_with_board(now_datetime(), body_type="Examination Committee")
		with self.assertRaisesRegex(frappe.ValidationError, "approve"):
			self.publish_with_board(now_datetime(), decision="Deferred")
		self.assertEqual(frappe.db.get_value("Exam Session", self.session.name, "status"), "Marks Entry")

	def test_the_resolution_must_name_this_session(self):
		self.ready()
		with self.assertRaisesRegex(frappe.ValidationError, "session"):
			self.publish_with_board(now_datetime(), session="")  # a resolution bound to no session
		with self.assertRaisesRegex(frappe.ValidationError, "session"):
			self.publish_with_board(now_datetime(), session=self.pre_session.name)

	def test_the_meeting_must_be_held_after_the_runs_completed(self):
		self.ready()
		with self.assertRaisesRegex(frappe.ValidationError, "Held"):
			self.publish_with_board(now_datetime(), held=False)
		with self.assertRaisesRegex(frappe.ValidationError, "Result Run"):
			self.publish_with_board(now_datetime(), days=-5)  # before the run finished (2 days ago)

	def test_every_programme_run_must_be_complete_and_none_in_flight(self):
		self.run_session()
		with self.assertRaisesRegex(frappe.ValidationError, "Result Run"):
			self.publish_with_board(now_datetime())  # results computed, but no finished run of the programme
		self.complete_run()
		self.complete_run(status="Running")
		with self.assertRaisesRegex(frappe.ValidationError, "still running"):
			self.publish_with_board(now_datetime())

	def test_the_meeting_owner_cannot_publish_and_release_at_is_required(self):
		self.ready()
		meeting, resolution = self.meeting()
		frappe.db.set_value("Body Meeting", meeting, "owner", COE_USER)
		frappe.set_user(COE_USER)
		with self.assertRaisesRegex(frappe.ValidationError, "recorded"):
			publication.publish_results(self.session.name, now_datetime(), meeting, resolution)
		frappe.set_user("Administrator")
		meeting, resolution = self.meeting()
		frappe.set_user(COE_USER)
		with self.assertRaisesRegex(frappe.ValidationError, "Release"):
			publication.publish_results(self.session.name, "", meeting, resolution)

	def test_only_the_coe_publishes_and_never_without_results(self):
		with self.assertRaises(frappe.ValidationError):
			self.publish_with_board(now_datetime())  # no Student Result yet
		self.ready()
		with self.assertRaises(frappe.PermissionError):
			self.publish_with_board(now_datetime(), user=FACULTY)

	def test_the_status_cannot_be_set_to_published_by_hand(self):
		session = frappe.get_doc("Exam Session", self.session.name)
		session.status, session.publish_at = "Published", now_datetime()
		with self.assertRaisesRegex(frappe.ValidationError, "Passing Board"):
			session.save()

	def test_one_resolution_publishes_one_session(self):
		self.ready()
		meeting, resolution = self.meeting()
		frappe.set_user(COE_USER)
		publication.publish_results(self.session.name, now_datetime(), meeting, resolution)
		frappe.db.set_value("Meeting Resolution", {"resolution_no": resolution}, "exam_session", self.pre_session.name)
		results.compute_student_result(self.s22.name, self.pre_session.name)
		frappe.set_user("Administrator")
		self.complete_run(self.pre_session)
		frappe.set_user(COE_USER)
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			publication.publish_results(self.pre_session.name, now_datetime(), meeting, resolution)


class TestReleaseNotice(PassingBoardFixture):
	def test_the_notice_goes_out_once_at_release(self):
		names = self.ready()
		self.publish_with_board(add_days(now_datetime(), 1))
		with patch.object(publication, "run_bulk") as run_bulk:
			publication.notify_released_results()
			run_bulk.assert_not_called()  # not yet released
			frappe.db.set_value("Exam Session", self.session.name, "publish_at", add_days(now_datetime(), -1))
			publication.notify_released_results()
			publication.notify_released_results()  # a second scheduler tick sends nothing more
		run_bulk.assert_called_once()
		self.assertEqual(sorted(run_bulk.call_args.args[1]), sorted(names.values()))
		self.assertTrue(frappe.db.get_value("Exam Session", self.session.name, "results_notified_on"))

	def test_each_student_and_guardian_gets_the_notice(self):
		names = self.run_session()
		with patch.object(publication, "send") as send:
			publication.notify_result(names[self.s22.name], None)
		event, doc, recipients = send.call_args.args
		guardian = frappe.db.get_value("Guardian", {"user": GUARDIAN_USER})
		self.assertEqual((event, doc.name), (publication.RELEASE_EVENT, names[self.s22.name]))
		self.assertEqual(recipients, [f"Student:{self.s22.name}", f"Guardian:{guardian}"])

	def test_the_release_template_is_seeded(self):
		self.assertTrue(frappe.db.get_value("Message Template", publication.RELEASE_EVENT, "enabled"))


class TestClassificationInputs(ResultFixture):
	def setUp(self):
		super().setUp()
		frappe.db.set_value("Exam Session", self.session.name, "is_final_year", 1)
		self.set_ese(self.s22, "EXM FA", 40)  # every course passed

	def test_a_final_year_result_without_arrears_is_classified(self):
		self.run_session()
		# CGPA (36 + 21 + 16 + 36 + 24) / 16 = 8.31: R2022 First Class (Distinction needs 8.5)
		doc = self.latest(self.s22)
		self.assertEqual((doc.cgpa, doc.arrear_count, doc.classification), (8.31, 0, "First Class"))
		self.assertFalse(self.latest(self.s26).classification)  # an arrear: no class yet

	def test_the_entry_type_reaches_the_classification(self):
		frappe.db.set_value("Student", self.s22.name, "oc_lateral_entry", 1)
		with patch.object(results.rules, "classify", wraps=results.rules.classify) as classify:
			results.compute_student_result(self.s22.name, self.pre_session.name)
			results.compute_student_result(self.s22.name, self.session.name)
		self.assertEqual(classify.call_args.kwargs["entry_type"], "Lateral")


class TestLateralDistinctionPatch(ResultFixture):
	def test_existing_r2022_distinction_rows_get_four_lateral_years(self):
		regulation22 = frappe.db.get_value("Student", self.s22.name, "oc_regulation")
		regulation26 = frappe.db.get_value("Student", self.s26.name, "oc_regulation")
		rows = frappe.qb.DocType("Classification Rule Class")
		frappe.qb.update(rows).set(rows.max_years_lateral, 0).run()  # as seeded before the field existed
		seed.fill_lateral_distinction_years()
		rule22 = frappe.get_doc("Classification Rule", {"regulation": regulation22})
		rule26 = frappe.get_doc("Classification Rule", {"regulation": regulation26})
		self.assertEqual(
			{(r.class_name, r.variant): r.max_years_lateral for r in rule22.classes if r.class_name == "First Class with Distinction"},
			{("First Class with Distinction", "Regular"): 4, ("First Class with Distinction", "Honours"): 4},
		)
		self.assertEqual({r.max_years_lateral for r in rule22.classes if r.class_name != "First Class with Distinction"}, {0})
		self.assertEqual({r.max_years_lateral for r in rule26.classes}, {0})
