"""M06-06 integration tests of photocopy, revaluation and review (P2-T20): eligibility by the regulation's course
types, the window from publication, the photocopy -> faculty justification -> revaluation step (R2022 16.4), review
only after a revaluation of the course, the fee as a Sales Invoice, the Revaluation Outcome by a different examiner
making a pending Student Result version that a Result Ratification publishes (grade sheet re-issued), and the
Revaluation Change Stats / Evaluation Grievances vs Appeared reports with the evaluation_grievances data point.

Fixture world: campus.tests.test_results.ExamFixture. s22 (R2022) has EXM FA at CIA 33.6 + ESE 26.4 = 60, ESE 44 %
< 45 %: U (Fail); EXM LB is a lab, EXM TL theory with lab; s_ab was absent from EXM TH; s_sa is short of
attendance. SGPA 8.11, CGPA (with EXM PRE 90 -> A+ 9, 4 credits) (73 + 36) / 13 = 8.38.
"""

from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from frappe.utils import add_days, flt, now_datetime, today

from campus.campus_platform.approvals import approve, request_approval
from campus.campus_platform.verification import issue
from campus.campus_finance.fee_heads import EXAM, set_item_default
from campus.examinations import revaluation, setup
from campus.examinations.report.evaluation_grievances_vs_appeared.evaluation_grievances_vs_appeared import (
	execute as grievance_report,
)
from campus.examinations.report.revaluation_change_stats.revaluation_change_stats import execute as change_report
from campus.iqac.registry import data_point
from campus.tests.finance_factories import ensure_fiscal_years, ensure_selling_setup, make_account
from campus.tests.test_exam_registration import with_customer
from campus.tests.test_regulation import year_name
from campus.tests.test_result_processing import APPROVER, RATIFICATION, ResultFixture
from campus.tests.factories import make_company
from campus.tests.test_results import COLLEGE, COE_USER, FACULTY, OTHER_FACULTY, make_instructor, make_login

APPLICATION, OUTCOME = "Revaluation Application", "Revaluation Outcome"
REVALUER = "exam-revaluer@example.com"
FEES = {"photocopy_fee": 300, "revaluation_fee": 500, "review_fee": 700}
WINDOW_DAYS = 10
OTHER_COLLEGE = "Reval Other College"


class RevaluationFixture(ResultFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_fiscal_years()
		ensure_selling_setup()
		income = f"Sales - {frappe.db.get_value('Company', COLLEGE, 'abbr')}"
		cost_center = frappe.db.get_value("Cost Center", {"company": COLLEGE, "is_group": 0}, "name")
		set_item_default(frappe.db.get_value("Fee Category", {"oc_fee_head_type": EXAM}), COLLEGE, income, cost_center)
		cls.bank = make_account(COLLEGE, "EXTC", "Collection Bank", "Bank Accounts", account_type="Bank", root_type="Asset")
		for student in (cls.s22, cls.s26):
			with_customer(student.name)
		make_login(REVALUER, "Instructor")
		cls.revaluer = make_instructor(REVALUER)
		# EXM FA and EXM TL are taught by OTHER_FACULTY (the justifying teacher), EXM TH by FACULTY
		for offering_name in (cls.offerings22["EXM FA"], cls.offerings22["EXM TL"], cls.pre_offering):  # and EXM PRE
			offering = frappe.get_doc("Student Group", offering_name)
			offering.append("instructors", {"instructor": cls.other_instructor})
			offering.save()

	def setUp(self):
		super().setUp()
		frappe.db.delete("Exam Fee Rate", {"company": COLLEGE})
		frappe.get_doc({"doctype": "Exam Fee Rate", "company": COLLEGE, "fee_per_course": 100, **FEES}).insert()
		for student, after_photocopy in ((self.s22, 1), (self.s26, 0)):
			frappe.db.set_value(
				"Exam Rule Set", {"regulation": self.regulation(student)},
				{"revaluation_window_days": WINDOW_DAYS, "revaluation_after_photocopy": after_photocopy},
			)  # fmt: skip
		self.v1 = self.run_session()[self.s22.name]
		self.publish(add_days(now_datetime(), -1))
		send = patch("campus.examinations.revaluation.send")
		self.sent = send.start()
		self.addCleanup(send.stop)

	# ---- helpers ------------------------------------------------------------------------------

	def regulation(self, student):
		return frappe.db.get_value("Student", student.name, "oc_regulation")

	def apply(self, kind, courses, student=None, submit=True, session=None):
		doc = frappe.get_doc(
			{
				"doctype": APPLICATION, "student": (student or self.s22).name, "exam_session": (session or self.session).name,
				"application_type": kind, "courses": [{"course": c} for c in courses],
			}
		).insert()  # fmt: skip
		if submit:
			doc.submit()
		return doc.reload()

	def pay(self, application):
		invoice = frappe.get_doc("Sales Invoice", frappe.db.get_value(APPLICATION, application.name, "fee_invoice"))
		payment = get_payment_entry("Sales Invoice", invoice.name, party_amount=invoice.outstanding_amount, bank_account=None)
		payment.paid_to = self.bank
		payment.reference_no, payment.reference_date = f"RV-{invoice.name}", today()
		payment.insert()
		payment.submit()
		return invoice.reload()

	def justify(self, application, course, user=OTHER_FACULTY):
		frappe.set_user(user)
		try:
			revaluation.justify(application.name, course, "The answer to Q4 is not valued")
		finally:
			frappe.set_user("Administrator")

	def photocopy(self, courses, session=None):
		doc = self.apply(revaluation.PHOTOCOPY, courses, session=session)
		self.pay(doc)
		revaluation.issue_photocopy(doc.name)
		return doc.reload()

	def revaluation_paid(self, courses=("EXM FA",), session=None):
		self.photocopy(courses, session)
		doc = self.apply(revaluation.REVALUATION, courses, submit=False, session=session)
		for course in courses:
			self.justify(doc, course)
		doc.reload().submit()
		self.pay(doc)
		return doc.reload()

	def outcome(self, application, course, new_ese, user=REVALUER, submit=True):
		doc = frappe.get_doc(
			{
				"doctype": OUTCOME, "application": application.name, "course": course, "examiner_type": "Internal",
				"employee": frappe.db.get_value("Employee", {"user_id": user}), "new_ese": new_ese,
			}
		).insert()  # fmt: skip
		if submit:
			doc.submit()
		return doc.reload()

	def ratify(self, session=None):
		"""Ratify the pending versions through the approval engine (the policy is ResultFixture's)."""
		frappe.set_user(COE_USER)
		doc = frappe.get_doc({"doctype": RATIFICATION, "exam_session": (session or self.session).name, "reason": "Revaluation outcomes"}).insert()
		request = request_approval(RATIFICATION, doc.name)
		frappe.set_user(APPROVER)
		try:
			with patch("campus.examinations.doctype.result_ratification.result_ratification.send"):
				approve(request)
		finally:
			frappe.set_user("Administrator")
		return doc.reload()

	def earlier_examiner(self, student, course, examiner):
		"""The script of `student` in `course` was valued by `examiner` (round 1)."""
		dummy = frappe.generate_hash(length=8)
		map_row = frappe.get_doc(
			{"doctype": "Dummy Number Map", "exam_session": self.session.name, "company": COLLEGE, "course": course,
			"student": student.name, "dummy_number": dummy, "finalised": 1}
		)  # fmt: skip
		map_row.name = f"DNM-{dummy}"
		map_row.db_insert()
		entry = frappe.get_doc(
			{"doctype": "Valuation Entry", "dummy_number": dummy, "valuation_round": "1", "exam_session": self.session.name,
			"course": course, "examiner": examiner, "docstatus": 1, "total": 26.4}
		)  # fmt: skip
		entry.name = f"VE-{dummy}"
		entry.db_insert()


class TestEligibility(RevaluationFixture):
	def test_a_lab_course_is_refused_by_the_rule_and_theory_with_lab_is_accepted(self):
		with self.assertRaisesRegex(frappe.ValidationError, "EXM LB.*not eligible"):
			self.apply(revaluation.PHOTOCOPY, ["EXM LB"])
		with self.assertRaisesRegex(frappe.ValidationError, "EXM LB.*not eligible"):
			self.apply(revaluation.REVALUATION, ["EXM LB"], student=self.s26)
		doc = self.apply(revaluation.PHOTOCOPY, ["EXM TL", "EXM FA"])
		self.assertEqual([(r.course, r.course_type) for r in doc.courses], [("EXM TL", "Theory with Lab"), ("EXM FA", "Theory")])

	def test_the_window_counts_from_publication(self):
		self.publish(add_days(now_datetime(), 1))  # not yet released
		with self.assertRaisesRegex(frappe.ValidationError, "window"):
			self.apply(revaluation.PHOTOCOPY, ["EXM FA"])
		self.publish(add_days(now_datetime(), -WINDOW_DAYS))  # day 10: the last day
		self.apply(revaluation.PHOTOCOPY, ["EXM FA"])
		self.publish(add_days(now_datetime(), -(WINDOW_DAYS + 1)))  # day 11
		with self.assertRaisesRegex(frappe.ValidationError, "window"):
			self.apply(revaluation.PHOTOCOPY, ["EXM TH"])
		frappe.db.set_value("Exam Rule Set", {"regulation": self.regulation(self.s22)}, "revaluation_window_days", 0)
		self.publish(add_days(now_datetime(), -1))
		with self.assertRaisesRegex(frappe.ValidationError, "window"):
			self.apply(revaluation.PHOTOCOPY, ["EXM TH"])

	def test_the_window_is_checked_again_on_submit(self):
		doc = self.apply(revaluation.PHOTOCOPY, ["EXM FA"], submit=False)
		self.publish(add_days(now_datetime(), -(WINDOW_DAYS + 1)))
		with self.assertRaisesRegex(frappe.ValidationError, "window"):
			doc.submit()

	def test_only_a_sat_course_of_the_published_result_is_eligible(self):
		with self.assertRaisesRegex(frappe.ValidationError, "EXM TH.*not sat"):
			self.apply(revaluation.PHOTOCOPY, ["EXM TH"], student=self.s_ab)
		with self.assertRaisesRegex(frappe.ValidationError, "EXM PRE.*not on the published result"):
			self.apply(revaluation.PHOTOCOPY, ["EXM PRE"])

	def test_one_live_application_of_a_type_per_course(self):
		self.apply(revaluation.PHOTOCOPY, ["EXM FA"])
		with self.assertRaisesRegex(frappe.ValidationError, "already applied"):
			self.apply(revaluation.PHOTOCOPY, ["EXM TH", "EXM FA"])
		with self.assertRaisesRegex(frappe.ValidationError, "twice"):
			self.apply(revaluation.PHOTOCOPY, ["EXM TH", "EXM TH"])

	def test_an_r2022_revaluation_needs_the_photocopy_and_a_teachers_justification(self):
		with self.assertRaisesRegex(frappe.ValidationError, "photocopy"):
			self.apply(revaluation.REVALUATION, ["EXM FA"], submit=False)
		applied = self.apply(revaluation.PHOTOCOPY, ["EXM FA"])
		with self.assertRaisesRegex(frappe.ValidationError, "photocopy"):  # applied and paid for, not yet issued
			self.apply(revaluation.REVALUATION, ["EXM FA"], submit=False)
		self.pay(applied)
		revaluation.issue_photocopy(applied.name)
		doc = self.apply(revaluation.REVALUATION, ["EXM FA"], submit=False)
		with self.assertRaisesRegex(frappe.ValidationError, "justification"):
			doc.submit()
		with self.assertRaises(frappe.PermissionError):  # FACULTY does not teach EXM FA
			self.justify(doc, "EXM FA", user=FACULTY)
		self.justify(doc, "EXM FA")
		doc.reload()
		row = doc.courses[0]
		self.assertEqual((row.justified_by, row.justification), (OTHER_FACULTY, "The answer to Q4 is not valued"))
		row.justified_by = FACULTY  # a client cannot rewrite who justified it
		doc.save()
		self.assertEqual(doc.reload().courses[0].justified_by, OTHER_FACULTY)
		doc.submit()
		self.assertEqual(doc.docstatus, 1)

	def test_r2026_revaluation_goes_without_a_photocopy(self):
		doc = self.apply(revaluation.REVALUATION, ["EXM FA"], student=self.s26)
		self.assertEqual(doc.docstatus, 1)

	def test_review_only_after_a_revaluation_of_that_course(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Review.*revaluation"):
			self.apply(revaluation.REVIEW, ["EXM FA"])
		reval = self.revaluation_paid(["EXM FA"])
		with self.assertRaisesRegex(frappe.ValidationError, "Review.*revaluation"):  # applied, no outcome yet
			self.apply(revaluation.REVIEW, ["EXM FA"])
		self.outcome(reval, "EXM FA", 40)
		with self.assertRaisesRegex(frappe.ValidationError, "EXM TL.*Review.*revaluation"):
			self.apply(revaluation.REVIEW, ["EXM TL"])
		self.assertEqual(self.apply(revaluation.REVIEW, ["EXM FA"]).docstatus, 1)


class TestFee(RevaluationFixture):
	def test_the_fee_is_a_sales_invoice_of_the_exam_head(self):
		doc = self.apply(revaluation.PHOTOCOPY, ["EXM TL", "EXM FA"])
		self.assertEqual(flt(doc.fee_amount), 600)  # 2 x 300
		invoice = frappe.get_doc("Sales Invoice", doc.fee_invoice)
		self.assertEqual((invoice.docstatus, flt(invoice.grand_total), invoice.student), (1, 600, self.s22.name))
		self.assertEqual(frappe.db.get_value("Fee Category", invoice.items[0].item_code, "oc_fee_head_type"), EXAM)
		self.assertFalse(revaluation.fee_paid(doc))
		with self.assertRaisesRegex(frappe.ValidationError, "fee"):
			revaluation.issue_photocopy(doc.name)
		self.pay(doc)
		self.assertTrue(revaluation.fee_paid(doc.reload()))
		revaluation.issue_photocopy(doc.name)
		self.assertTrue(doc.reload().photocopy_issued_on)

	def test_no_outcome_before_the_fee_is_paid(self):
		self.photocopy(["EXM FA"])
		doc = self.apply(revaluation.REVALUATION, ["EXM FA"], submit=False)
		self.justify(doc, "EXM FA")
		doc.reload().submit()
		self.assertEqual(flt(doc.reload().fee_amount), 500)
		with self.assertRaisesRegex(frappe.ValidationError, "fee"):
			self.outcome(doc, "EXM FA", 40, submit=False)

	def test_cancel_cancels_the_unpaid_invoice_and_is_refused_once_paid(self):
		doc = self.apply(revaluation.PHOTOCOPY, ["EXM FA"])
		invoice = doc.fee_invoice
		doc.cancel()
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice, "docstatus"), 2)
		paid = self.apply(revaluation.PHOTOCOPY, ["EXM FA"])
		self.pay(paid)
		with self.assertRaisesRegex(frappe.ValidationError, "paid"):
			paid.reload().cancel()

	def test_only_the_coe_issues_a_photocopy(self):
		doc = self.apply(revaluation.PHOTOCOPY, ["EXM FA"])
		self.pay(doc)
		frappe.set_user(FACULTY)
		with self.assertRaises(frappe.PermissionError):
			revaluation.issue_photocopy(doc.name)


class TestOutcome(RevaluationFixture):
	def test_an_upward_change_makes_a_ratified_version_regrades_and_reissues_the_grade_sheet(self):
		old_sheet = issue(frappe.get_doc("Student Result", self.v1), "Grade Sheet")
		reval = self.revaluation_paid(["EXM FA"])
		outcome = self.outcome(reval, "EXM FA", 40)  # 33.6 + 40 = 73.6 -> A
		self.assertEqual((outcome.original_ese, outcome.new_ese, outcome.ese_change), (26.4, 40, 13.6))
		self.assertEqual((outcome.original_grade, outcome.revised_grade), ("U", "A"))
		v2 = frappe.get_doc("Student Result", outcome.result_version)
		self.assertEqual((v2.version, v2.pending_ratification, v2.is_latest, v2.previous_version), (2, 1, 0, self.v1))
		self.assertIn("EXM FA: U (Fail) -> A (Pass), total 60 -> 73.6", v2.change_log)
		self.assertEqual(frappe.db.get_value("Student Result", self.v1, "is_latest"), 1)  # published stays until ratified
		self.assertEqual(self.sent.call_args.args[0], revaluation.OUTCOME_EVENT)
		self.assertEqual(self.sent.call_args.args[2], [f"Student:{self.s22.name}"])
		self.ratify()
		v1, v2 = frappe.get_doc("Student Result", self.v1), v2.reload()
		self.assertEqual((v1.is_latest, v2.is_latest, v2.pending_ratification), (0, 1, 0))
		self.assertEqual((flt(v1.sgpa), flt(v1.cgpa), flt(v2.sgpa), flt(v2.cgpa)), (8.11, 8.38, 8.08, 8.31))  # 97/12, 133/16
		self.assertEqual(frappe.db.get_value("Verifiable Document", old_sheet.name, "status"), "Revoked")
		new_sheet = frappe.get_all(
			"Verifiable Document", {"reference_doctype": "Student Result", "reference_name": v2.name, "status": "Valid"},
			["print_format"],
		)  # fmt: skip
		self.assertEqual([s.print_format for s in new_sheet], ["Grade Sheet"])
		history = frappe.get_all("Student Result", {"student": self.s22.name, "exam_session": self.session.name}, ["version", "previous_version"], order_by="version")
		self.assertEqual([(h.version, h.previous_version) for h in history], [(1, None), (2, self.v1)])

	def test_no_grade_sheet_is_issued_when_none_was(self):
		reval = self.revaluation_paid(["EXM FA"])
		self.outcome(reval, "EXM FA", 40)
		self.ratify()
		self.assertFalse(frappe.db.exists("Verifiable Document", {"reference_doctype": "Student Result", "reference_name": ["like", f"SR-{self.session.name}-{self.s22.name}%"]}))

	def test_an_unchanged_mark_makes_no_version(self):
		reval = self.revaluation_paid(["EXM FA"])
		outcome = self.outcome(reval, "EXM FA", 26.4)
		self.assertEqual((outcome.ese_change, outcome.result_version, outcome.revised_grade), (0, self.v1, "U"))
		self.assertEqual(frappe.db.count("Student Result", {"student": self.s22.name, "exam_session": self.session.name}), 1)

	def test_a_review_outcome_supersedes_the_revaluation_mark(self):
		reval = self.revaluation_paid(["EXM FA"])
		self.outcome(reval, "EXM FA", 40)
		review = self.apply(revaluation.REVIEW, ["EXM FA"])
		self.pay(review)
		with self.assertRaisesRegex(frappe.ValidationError, "revalued"):  # the revaluer does not review
			self.outcome(review, "EXM FA", 45, submit=False)
		outcome = self.outcome(review, "EXM FA", 45, user=FACULTY)  # 33.6 + 45 = 78.6 -> A
		self.assertEqual((outcome.original_ese, outcome.ese_change), (40, 5))
		self.assertEqual(outcome.original_grade, "A")  # the grade of the pending version the revaluation made, not U
		row = next(c for c in frappe.get_doc("Student Result", outcome.result_version).courses if c.course == "EXM FA")
		self.assertEqual((row.ese, row.total, row.grade), (45, 78.6, "A"))

	def test_the_revaluer_is_not_an_earlier_examiner_nor_a_teacher_of_the_course(self):
		reval = self.revaluation_paid(["EXM FA"])
		self.earlier_examiner(self.s22, "EXM FA", REVALUER)
		with self.assertRaisesRegex(frappe.ValidationError, "valued this script"):
			self.outcome(reval, "EXM FA", 40, submit=False)
		with self.assertRaisesRegex(frappe.ValidationError, "teaches"):
			self.outcome(reval, "EXM FA", 40, user=OTHER_FACULTY, submit=False)
		self.assertEqual(self.outcome(reval, "EXM FA", 40, user=FACULTY).docstatus, 1)

	def test_the_revaluer_does_not_record_their_own_outcome(self):
		reval = self.revaluation_paid(["EXM FA"])
		doc = frappe.get_doc(
			{"doctype": OUTCOME, "application": reval.name, "course": "EXM FA", "examiner_type": "Internal",
			"employee": frappe.db.get_value("Employee", {"user_id": REVALUER}), "new_ese": 40}
		)  # fmt: skip
		frappe.set_user(REVALUER)
		with self.assertRaisesRegex(frappe.ValidationError, "own"):
			doc.insert(ignore_permissions=True)

	def test_the_outcome_is_bound_to_its_application(self):
		reval = self.revaluation_paid(["EXM FA"])
		with self.assertRaisesRegex(frappe.ValidationError, "EXM TH.*not on"):
			self.outcome(reval, "EXM TH", 30, submit=False)
		with self.assertRaisesRegex(frappe.ValidationError, "0-60"):
			self.outcome(reval, "EXM FA", 61, submit=False)
		self.outcome(reval, "EXM FA", 40)
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			self.outcome(reval, "EXM FA", 41, submit=False)
		photocopy = frappe.get_all(APPLICATION, {"application_type": revaluation.PHOTOCOPY, "docstatus": 1}, pluck="name")[0]
		with self.assertRaisesRegex(frappe.ValidationError, "Photocopy"):
			self.outcome(frappe.get_doc(APPLICATION, photocopy), "EXM FA", 40, submit=False)

	def test_an_outcome_cannot_be_cancelled_nor_its_application(self):
		reval = self.revaluation_paid(["EXM FA"])
		outcome = self.outcome(reval, "EXM FA", 40)
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be cancelled"):
			outcome.cancel()
		with self.assertRaisesRegex(frappe.ValidationError, "outcome"):
			reval.reload().cancel()

	def test_the_outcome_template_is_seeded(self):
		frappe.db.delete("Message Template", {"event_key": revaluation.OUTCOME_EVENT})
		setup.setup_examinations()
		self.assertTrue(frappe.db.exists("Message Template", revaluation.OUTCOME_EVENT))


class TestReports(RevaluationFixture):
	def test_revaluation_change_stats(self):
		reval = self.revaluation_paid(["EXM FA", "EXM TL"])
		self.outcome(reval, "EXM FA", 40)  # up 13.6, U -> A
		self.outcome(reval, "EXM TL", 45)  # unchanged
		_columns, rows = change_report({"company": COLLEGE, "exam_session": self.session.name})
		by_course = {r["course"]: r for r in rows}
		self.assertEqual(
			{c: (r["outcomes"], r["increased"], r["decreased"], r["unchanged"], r["grade_changed"], r["average_change"]) for c, r in by_course.items()},
			{"EXM FA": (1, 1, 0, 0, 1, 13.6), "EXM TL": (1, 0, 0, 1, 0, 0)},
		)
		self.assertEqual(change_report({"company": "Another College"})[1], [])

	def test_evaluation_grievances_vs_appeared_and_the_data_point(self):
		# appeared: s22, s26 and s_ab (sat the other courses); s_sa sat nothing (SA). Grievances: s22 (a revaluation;
		# the photocopy alone is not a grievance) and s26 (a photocopy only) -> 1 of 3
		reval = self.revaluation_paid(["EXM FA"])
		self.apply(revaluation.PHOTOCOPY, ["EXM FA"], student=self.s26)
		_columns, rows = grievance_report({"company": COLLEGE, "academic_year": year_name("2022")})
		row = next(r for r in rows if r["exam_session"] == self.session.name)
		self.assertEqual((row["appeared"], row["grievances"], row["grievance_pct"]), (3, 1, 33.33))
		point = data_point("evaluation_grievances", COLLEGE, year_name("2022"))
		self.assertEqual(point["value"], 1)
		self.assertEqual(point["records"], [{"doctype": APPLICATION, "name": reval.name}])
		self.assertEqual(data_point("evaluation_grievances", COLLEGE, year_name("2026"))["value"], 0)



class TestLaterSessions(RevaluationFixture):
	def test_a_ratified_revaluation_refreshes_the_later_sessions_results(self):
		# EXM PRE (pre_session) 36 + 54 = 90 -> A+ 9; revalued to 60: 96 -> O 10. The later session's CGPA (with its
		# own 73 grade-point credits over 9) moves from (73 + 36) / 13 = 8.38 to (73 + 40) / 13 = 8.69.
		frappe.db.set_value("Exam Session", self.pre_session.name, {"status": "Published", "publish_at": add_days(now_datetime(), -1)})
		later = frappe.db.get_value("Student Result", {"student": self.s22.name, "exam_session": self.session.name, "is_latest": 1})
		reval = self.revaluation_paid(["EXM PRE"], session=self.pre_session)
		self.outcome(reval, "EXM PRE", 60)
		self.assertFalse(frappe.db.exists("Student Result", {"exam_session": self.session.name, "pending_ratification": 1}))
		self.ratify(session=self.pre_session)
		pending = frappe.get_doc("Student Result", {"student": self.s22.name, "exam_session": self.session.name, "pending_ratification": 1})
		self.assertEqual((flt(pending.cgpa), pending.previous_version), (8.69, later))
		self.assertIn("CGPA: 8.38 -> 8.69", pending.change_log)
		self.assertEqual(frappe.db.get_value("Student Result", later, "is_latest"), 1)  # until its own ratification


class TestInstructorAccess(RevaluationFixture):
	def visible(self, user):
		frappe.set_user(user)
		try:
			return frappe.get_list(APPLICATION, pluck="name")
		finally:
			frappe.set_user("Administrator")

	def test_a_teacher_of_the_course_opens_and_justifies_the_draft_and_no_one_else_sees_it(self):
		self.photocopy(["EXM FA"])
		draft = self.apply(revaluation.REVALUATION, ["EXM FA"], submit=False)
		self.assertEqual(self.visible(OTHER_FACULTY), [draft.name])  # teaches EXM FA
		self.assertTrue(frappe.has_permission(APPLICATION, "read", draft, user=OTHER_FACULTY))
		self.assertFalse(frappe.has_permission(APPLICATION, "write", draft, user=OTHER_FACULTY))
		self.assertEqual(self.visible(FACULTY), [])  # teaches EXM TH only
		self.assertFalse(frappe.has_permission(APPLICATION, "read", draft, user=FACULTY))
		self.justify(draft, "EXM FA")
		draft.reload().submit()
		self.assertEqual(self.visible(OTHER_FACULTY), [])  # drafts only
		self.assertFalse(frappe.has_permission(APPLICATION, "read", draft.reload(), user=OTHER_FACULTY))

	def test_a_non_teacher_learns_nothing_from_justify(self):
		doc = self.apply(revaluation.PHOTOCOPY, ["EXM FA"])  # submitted, and not a revaluation
		with self.assertRaises(frappe.PermissionError):
			self.justify(doc, "EXM FA", user=FACULTY)


class TestFeeSafety(RevaluationFixture):
	def test_a_blank_fee_rate_refuses_the_submit(self):
		frappe.db.set_value("Exam Fee Rate", {"company": COLLEGE}, "photocopy_fee", 0)
		doc = self.apply(revaluation.PHOTOCOPY, ["EXM FA"], submit=False)
		with self.assertRaisesRegex(frappe.ValidationError, "Photocopy Fee"):
			doc.submit()

	def test_the_coe_raises_a_missing_invoice_again(self):
		doc = self.apply(revaluation.PHOTOCOPY, ["EXM FA"])
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			revaluation.reraise_fee(doc.name)
		frappe.db.set_value(APPLICATION, doc.name, "fee_invoice", None)  # as if the invoice job had failed
		revaluation.reraise_fee(doc.name)
		invoice = frappe.db.get_value(APPLICATION, doc.name, "fee_invoice")
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice, "grand_total")), 300)
		frappe.set_user(FACULTY)
		with self.assertRaises(frappe.PermissionError):
			revaluation.reraise_fee(doc.name)

	def test_issue_photocopy_respects_the_coes_company_restriction(self):
		doc = self.apply(revaluation.PHOTOCOPY, ["EXM FA"])
		self.pay(doc)
		make_company(OTHER_COLLEGE, "RVOC")
		frappe.get_doc({"doctype": "User Permission", "user": COE_USER, "allow": "Company", "for_value": OTHER_COLLEGE}).insert()
		frappe.set_user(COE_USER)
		with self.assertRaises(frappe.PermissionError):
			revaluation.issue_photocopy(doc.name)

	def test_a_failed_grade_sheet_job_is_logged_with_the_ratification(self):
		from campus.examinations.doctype.result_ratification import result_ratification

		before = frappe.db.count("Error Log")
		with patch("campus.campus_platform.verification.issue", side_effect=frappe.ValidationError("render failed")):
			result_ratification.issue_grade_sheet(self.v1, "RRAT-TEST")
		self.assertEqual(frappe.db.count("Error Log"), before + 1)
		log = frappe.get_all("Error Log", fields=["method", "error"], order_by="creation desc", limit=1)[0]
		self.assertIn("RRAT-TEST", log.method + (log.error or ""))
