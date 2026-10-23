"""X-03 integration tests (M05-15): the credit completion check, Study Completed only on a Complete check, Award
Eligible only without dues and with the programme's degree-awarding authority in force, the dated move to Alumni,
bulk checks with per-student outcomes, and company scope.

Fixture: the graduation fixture (campus.tests.test_graduation): GRD C1-C4 are the mandatory 3-credit PCC courses of
each regulation's Effective curriculum, and the university's affiliation of the programme is Active until a year
ahead. "dist" passed all four, "arrear" failed GRD C4, "partial" registered for Honours with 9 of 18 credits.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from campus.campus_platform import bulk
from campus.campus_platform.approvals import approve, request_approval
from campus.examinations import completion, convocation
from campus.examinations.report.completion_status import completion_status
from campus.tests.factories import make_company, make_user
from campus.tests.test_graduation import COLLEGE, PROGRAM, GraduationFixture

OTHER_COLLEGE, OTHER_ABBR = "Grad Other College", "GRDO"
COE_USER, OTHER_COE, ACADEMICS = "grd-coe@example.com", "grd-other-coe@example.com", "grd-plain@example.com"
DEAN, DEAN_2 = "grd-dean@example.com", "grd-dean2@example.com"
EVIDENCE = "/private/files/grd-nptel-certificate.pdf"
NO_DUES = frappe._dict(blocking=0, by_company={})


def owing(student, amount=2500):
	"""has_dues stand-in: `student` owes `amount` to the college (the gate itself is campus_finance's, tested there)."""

	def dues(who, *args, **kwargs):
		return frappe._dict(blocking=amount, by_company={COLLEGE: amount}) if who == student else NO_DUES

	return patch.object(completion, "has_dues", side_effect=dues)


class CompletionCase(GraduationFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(OTHER_COLLEGE, OTHER_ABBR)
		users = (
			(COE_USER, COLLEGE, "COE"), (OTHER_COE, OTHER_COLLEGE, "COE"), (ACADEMICS, COLLEGE, None),
			(DEAN, COLLEGE, "Dean Academics"), (DEAN_2, COLLEGE, "Dean Academics"),
		)  # fmt: skip
		for email, company, role in users:
			make_user(email, [company])
			if role:
				frappe.get_doc("User", email).add_roles(role)

	def check(self, key):
		return completion.run_check(self.students[key])

	def category(self, check, name):
		return next(row for row in check.categories if row.category == name)

	def status(self, key):
		return frappe.db.get_value("Student", self.students[key], "oc_academic_status")

	def make_list(self, convocation_date=None):
		doc = frappe.get_doc({"doctype": "Convocation List", "company": COLLEGE, "program": PROGRAM, "convocation_date": convocation_date}).insert()
		convocation.fill_graduates(doc.name)
		return frappe.get_doc("Convocation List", doc.name)

	def row(self, doc, key):
		return next((g for g in doc.graduates if g.student == self.students[key]), None)

	def curriculum(self, key):
		return completion.check_facts(self.students[key]).curriculum

	def last_transition(self, key):
		return frappe.get_all(
			"Lifecycle Transition", {"student": self.students[key]}, ["kind", "from_status", "to_status", "effective_date"],
			order_by="creation desc, name desc", limit=1,
		)[0]  # fmt: skip

	def draft(self, key, course, kind="Waiver", credits=3, **values):
		return frappe.get_doc(
			{"doctype": "Credit Recognition", "student": self.students[key], "course": course, "kind": kind, "credits": credits,
			"source_course": "NPTEL equivalent", "evidence": EVIDENCE, **values}
		).insert()  # fmt: skip

	def approve(self, doc, approver=DEAN):
		"""Raise the approval as the record's owner and approve it as a Dean Academics of the college."""
		owner = frappe.session.user
		request = request_approval("Credit Recognition", doc.name)
		frappe.set_user(approver)
		approve(request, None)
		frappe.set_user(owner)
		doc.reload()
		self.assertEqual(doc.docstatus, 1)
		return doc

	def recognise(self, key, course, kind="Waiver", credits=3, submit=True):
		doc = self.draft(key, course, kind, credits)
		return self.approve(doc) if submit else doc


class TestCompletionCheck(CompletionCase):
	def test_a_complete_check_is_recorded_per_category(self):
		check = self.check("dist")
		self.assertEqual((check.result, check.missing_courses, check.program, check.curriculum), ("Complete", "", PROGRAM, self.curriculum("dist")))
		pcc = self.category(check, "PCC")
		self.assertEqual((pcc.earned_credits, pcc.status), (12, "Met"))

	def test_a_rerun_with_the_same_outcome_records_nothing_new(self):
		first = self.check("dist")
		self.assertEqual(self.check("dist").name, first.name)
		frappe.db.set_value("Student Result", {"student": self.students["dist"], "exam_session": self.s2}, "pending_ratification", 1)
		second = self.check("dist")
		self.assertNotEqual(second.name, first.name)
		self.assertEqual(frappe.db.count("Completion Check", {"student": self.students["dist"]}), 2)

	def test_incomplete_credits_block_study_completed(self):
		frappe.get_doc(
			{"doctype": "Category Credit Requirement", "parenttype": "Curriculum", "parentfield": "category_requirements",
			"parent": self.curriculum("dist"), "category": "PCC", "min_credits": 15}
		).db_insert()  # fmt: skip
		check = self.check("dist")
		self.assertEqual((check.result, self.category(check, "PCC").status), ("Incomplete", "Short"))
		self.assertIn("PCC: 12.0 of 15.0 credits", check.reasons)
		doc = self.make_list()
		self.assertIsNone(self.row(doc, "dist"))
		self.assertEqual(self.status("dist"), "Active")

	def test_a_result_pending_ratification_is_not_counted(self):
		frappe.db.set_value("Student Result", {"student": self.students["dist"], "exam_session": self.s2}, "pending_ratification", 1)
		check = self.check("dist")
		self.assertEqual((check.result, check.missing_courses), ("Incomplete", "GRD C3, GRD C4"))
		self.assertEqual(self.category(check, "PCC").earned_credits, 6)

	def test_a_mandatory_course_not_cleared_is_named(self):
		check = self.check("arrear")
		self.assertEqual((check.result, check.missing_courses), ("Incomplete", "GRD C4"))
		self.assertIn("Mandatory courses not cleared: GRD C4", check.reasons)

	def test_a_waiver_clears_a_course_and_counts_once(self):
		self.recognise("arrear", "GRD C4")
		check = self.check("arrear")
		self.assertEqual((check.result, self.category(check, "PCC").earned_credits), ("Complete", 12))
		self.recognise("dist", "GRD C1", kind="Equivalence")  # passed as well: counted once
		self.assertEqual(self.category(self.check("dist"), "PCC").earned_credits, 12)
		with self.assertRaisesRegex(frappe.ValidationError, "already recognised"):
			self.recognise("arrear", "GRD C4", kind="Transfer")

	def test_a_draft_or_cancelled_recognition_clears_nothing(self):
		draft = self.recognise("arrear", "GRD C4", submit=False)
		self.assertEqual(self.check("arrear").result, "Incomplete")
		self.approve(draft).cancel()  # the student is still Active: cancelling is allowed
		self.assertEqual(self.check("arrear").result, "Incomplete")

	def test_no_effective_curriculum_is_incomplete(self):
		frappe.db.set_value("Curriculum", self.curriculum("weak26"), "status", "Superseded")
		check = self.check("weak26")
		self.assertEqual((check.result, check.curriculum), ("Incomplete", None))
		self.assertIn("No Effective curriculum", check.reasons)

	def test_honours_credits_are_shown_and_do_not_block_the_degree(self):
		check = self.check("partial")
		honours = self.category(check, "Honours")
		self.assertEqual((honours.required_credits, honours.earned_credits, honours.status), (18, 9, "Not Required"))
		self.assertEqual(check.result, "Complete")

	def test_a_check_cannot_be_edited_or_deleted(self):
		check = frappe.get_doc("Completion Check", self.check("dist").name)
		check.result = "Incomplete"
		with self.assertRaisesRegex(frappe.ValidationError, "completion service only"):
			check.save(ignore_permissions=True)
		with self.assertRaisesRegex(frappe.ValidationError, "kept for audit"):
			frappe.delete_doc("Completion Check", check.name, ignore_permissions=True)


class TestAwardEligibility(CompletionCase):
	def test_dues_block_award_eligible_with_the_reason(self):
		with owing(self.students["dist"]):
			doc = self.make_list()
			self.assertEqual(self.status("dist"), "Study Completed")
			hold = self.row(doc, "dist").award_hold
			self.assertIn("Dues outstanding (Grad Test College: ", hold)
			self.assertIn("2,500", hold)
			self.assertEqual((self.status("cleared"), self.row(doc, "cleared").award_hold), ("Award Eligible", None))
			doc.db_set("convocation_date", today())
			result = convocation.graduate(doc.name)
		self.assertEqual(self.status("dist"), "Study Completed")
		self.assertEqual(result["graduated"], 4)
		self.assertEqual([r["student"] for r in result["refused"]], [self.students["dist"]])
		self.assertIn("Not award eligible: Dues outstanding", result["refused"][0]["reason"])

	def test_an_expired_affiliation_blocks_award_eligible_with_the_reason(self):
		affiliation = frappe.get_doc("Official Document", {"company": COLLEGE, "reference_no": "GRD-AFF-1"})
		affiliation.valid_to = add_days(today(), -1)
		affiliation.save()
		self.assertEqual(affiliation.status, "Expired")
		doc = self.make_list()
		hold = self.row(doc, "dist").award_hold
		self.assertIn("The Affiliation document GRD-AFF-1 of University for Grad Test BE is not in force", hold)
		self.assertIn("Expired", hold)
		self.assertEqual(self.status("dist"), "Study Completed")
		renewed = frappe.get_doc(
			{"doctype": "Official Document", "company": COLLEGE, "program": PROGRAM, "authority": "University",
			"document_type": "Affiliation", "reference_no": "GRD-AFF-2", "valid_from": today(), "valid_to": add_days(today(), 365)}
		).insert()  # fmt: skip
		affiliation.db_set("superseded_by", renewed.name)
		convocation.fill_graduates(doc.name)
		self.assertEqual(self.status("dist"), "Award Eligible")
		self.assertIsNone(self.row(frappe.get_doc("Convocation List", doc.name), "dist").award_hold)

	def test_a_college_wide_document_covers_the_programme(self):
		frappe.db.set_value("Official Document", {"reference_no": "GRD-AFF-1"}, "program", None)
		self.make_list()
		self.assertEqual(self.status("dist"), "Award Eligible")

	def test_a_programme_without_an_authority_is_held(self):
		frappe.db.delete("Degree Awarding Authority", {"company": COLLEGE, "program": PROGRAM})
		doc = self.make_list()
		self.assertIn("No Degree Awarding Authority is set for Grad Test BE", self.row(doc, "dist").award_hold)

	def test_the_authority_is_checked_again_on_the_convocation_date(self):
		doc = self.make_list()
		self.assertEqual(self.status("dist"), "Award Eligible")
		frappe.db.set_value("Official Document", {"reference_no": "GRD-AFF-1"}, "valid_to", add_days(today(), -3))
		doc.db_set("convocation_date", add_days(today(), -2))
		result = convocation.graduate(doc.name)
		self.assertEqual(result["graduated"], 0)
		self.assertEqual(len(result["refused"]), 5)
		self.assertIn("not in force", result["refused"][0]["reason"])
		self.assertEqual(self.status("dist"), "Award Eligible")

	def test_a_hold_after_award_eligible_is_undone_on_refill(self):
		doc = self.make_list()
		self.assertEqual(self.status("dist"), "Award Eligible")
		with owing(self.students["dist"]):
			convocation.fill_graduates(doc.name)
		self.assertEqual(self.status("dist"), "Study Completed")
		last = self.last_transition("dist")
		self.assertEqual((last.kind, last.from_status, last.to_status), ("Reversal", "Award Eligible", "Study Completed"))

	def test_the_listed_row_links_its_completion_check(self):
		doc = self.make_list()
		check = completion.latest_check(self.students["dist"])
		self.assertEqual((self.row(doc, "dist").completion_check, check.result), (check.name, "Complete"))
		first = frappe.get_all("Lifecycle Transition", {"student": self.students["dist"], "to_status": "Study Completed"}, pluck="reason")
		self.assertIn(check.name, first[0])


class TestAlumni(CompletionCase):
	def settings(self, move, days=30):
		frappe.db.set_single_value("Completion Settings", {"alumni_move": move, "alumni_after_days": days})

	def lifecycle_tail(self, key):
		row = self.last_transition(key)
		return (row.from_status, row.to_status, row.effective_date)

	def test_on_convocation_graduates_become_alumni_that_day(self):
		self.settings("On Convocation")
		held = getdate(add_days(today(), -5))
		doc = self.make_list(held)
		self.assertEqual(convocation.graduate(doc.name)["graduated"], 5)
		self.assertEqual(self.status("dist"), "Alumni")
		self.assertEqual(self.lifecycle_tail("dist"), ("Graduated", "Alumni", held))

	def test_the_daily_job_moves_graduates_the_set_days_after_graduation(self):
		self.settings("Days After Graduation", 30)
		held = getdate(add_days(today(), -40))
		doc = self.make_list(held)
		convocation.graduate(doc.name)
		self.assertEqual(self.status("dist"), "Graduated")
		self.assertEqual(completion.move_graduates_to_alumni(add_days(held, 29)), 0)  # not yet due
		self.assertEqual(self.status("dist"), "Graduated")
		self.assertGreaterEqual(completion.move_graduates_to_alumni(), 5)  # the site may hold other graduates
		self.assertEqual(self.lifecycle_tail("dist"), ("Graduated", "Alumni", getdate(add_days(held, 30))))
		self.assertEqual(self.status("weak26"), "Alumni")
		self.assertEqual(completion.move_graduates_to_alumni(), 0)  # once

	def test_in_on_convocation_mode_the_daily_job_moves_graduates_left_behind(self):
		self.settings("Days After Graduation", 30)
		held = getdate(add_days(today(), -3))
		convocation.graduate(self.make_list(held).name)  # graduated before the college switched to "On Convocation"
		self.settings("On Convocation")
		self.assertGreaterEqual(completion.move_graduates_to_alumni(), 5)
		self.assertEqual(self.lifecycle_tail("dist"), ("Graduated", "Alumni", held))


class TestBulkAndScope(CompletionCase):
	def run_bulk(self, user=COE_USER, **kwargs):
		frappe.set_user(user)
		with patch.object(bulk, "enqueue_run"), patch.object(frappe.db, "commit"):
			run = completion.run_completion_checks(COLLEGE, PROGRAM, **kwargs)
			bulk.process_bulk_run(run)
		frappe.set_user("Administrator")
		return frappe.get_doc("Bulk Run", run)

	def test_a_bulk_run_records_each_students_outcome(self):
		run = self.run_bulk()
		self.assertEqual((run.status, run.total, run.done, run.failed), ("Completed", 7, 7, 0))
		outcomes = dict(frappe.get_all("Completion Check", {"bulk_run": run.name}, ["student", "result"], as_list=True))
		self.assertEqual(outcomes[self.students["dist"]], "Complete")
		self.assertEqual(outcomes[self.students["arrear"]], "Incomplete")
		self.assertEqual(len(outcomes), 7)

	def test_a_second_run_records_every_students_outcome(self):
		first = self.run_bulk()
		second = self.run_bulk()
		outcomes = dict(frappe.get_all("Completion Check", {"bulk_run": second.name}, ["student", "result"], as_list=True))
		self.assertEqual(len(outcomes), 7)
		self.assertEqual(outcomes[self.students["arrear"]], "Incomplete")
		self.assertEqual(frappe.db.count("Completion Check", {"bulk_run": first.name}), 7)
		self.assertEqual(self.check("dist").bulk_run, second.name)  # a plain re-run records nothing new

	def test_a_failing_student_is_reported_and_the_rest_are_checked(self):
		real = completion.run_check

		def flaky(student, bulk_run=None):
			if student == self.students["arrear"]:
				frappe.throw("Curriculum unreadable")
			return real(student, bulk_run)

		with patch.object(completion, "run_check", side_effect=flaky):
			run = self.run_bulk()
		self.assertEqual((run.status, run.done, run.failed), ("Completed with errors", 6, 1))
		self.assertEqual(frappe.db.count("Completion Check", {"bulk_run": run.name}), 6)

	def test_a_batch_filter_limits_the_run(self):
		run = self.run_bulk(batch=frappe.db.get_value("Student", self.students["weak26"], "oc_batch"))
		self.assertEqual(run.total, 1)

	def test_only_the_coe_or_dean_runs_checks_of_their_own_college(self):
		frappe.set_user(ACADEMICS)
		with self.assertRaises(frappe.PermissionError):
			completion.run_completion_checks(COLLEGE, PROGRAM)
		frappe.set_user(OTHER_COE)
		with self.assertRaises(frappe.PermissionError):
			completion.run_completion_checks(COLLEGE, PROGRAM)
		with self.assertRaises(frappe.PermissionError):
			completion.check_student(self.students["dist"])
		frappe.set_user(COE_USER)
		self.assertEqual(completion.check_student(self.students["dist"])["result"], "Complete")

	def test_checks_and_the_report_are_company_scoped(self):
		self.check("dist")
		self.check("arrear")
		frappe.set_user(COE_USER)
		rows = completion_status.execute({"company": COLLEGE})[1]
		mine = next(r for r in rows if r["batch"] == frappe.db.get_value("Student", self.students["dist"], "oc_batch"))
		self.assertEqual((mine["checked"], mine["complete"], mine["incomplete"]), (2, 1, 1))
		self.assertTrue(frappe.get_list("Completion Check", {"student": self.students["dist"]}))
		frappe.set_user(OTHER_COE)
		self.assertEqual(completion_status.execute({"company": COLLEGE})[1], [])
		self.assertEqual(frappe.get_list("Completion Check", {"student": self.students["dist"]}), [])


class TestFixRound1(CompletionCase):
	"""X-03 review round 1: Credit Recognition is approved and checked; Mark Graduated re-evaluates; the authority is
	kept by the Principal and fits the awarding body."""

	def test_a_recognition_is_never_submitted_without_approval(self):
		doc = self.draft("arrear", "GRD C4")
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		frappe.db.delete("Approval Level", {"parent": "Credit Recognition Approval"})
		frappe.db.delete("Approval Policy", {"document_type": "Credit Recognition"})
		with self.assertRaisesRegex(frappe.ValidationError, "No approval policy is configured"):
			request_approval("Credit Recognition", doc.name)

	def test_the_maker_cannot_approve_their_own_recognition(self):
		frappe.set_user(DEAN)
		doc = self.draft("arrear", "GRD C4")
		request = request_approval("Credit Recognition", doc.name)
		with self.assertRaises(frappe.PermissionError):
			approve(request, None)
		frappe.set_user(DEAN_2)
		approve(request, None)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Credit Recognition", doc.name, "docstatus"), 1)

	def test_credits_are_required_except_for_a_waiver(self):
		with self.assertRaisesRegex(frappe.ValidationError, "credits granted"):
			self.draft("arrear", "GRD C4", kind="Transfer", credits=0)
		self.assertTrue(self.draft("arrear", "GRD C4", kind="Waiver", credits=0).name)

	def test_private_evidence_is_required(self):
		for evidence in (None, "/files/public-certificate.pdf", "/private/../files/x.pdf"):
			with self.assertRaisesRegex(frappe.ValidationError, "private file"):
				self.draft("arrear", "GRD C4", evidence=evidence)

	def test_the_course_must_be_on_the_students_curriculum(self):
		with self.assertRaisesRegex(frappe.ValidationError, "not a course of the student's Effective curriculum"):
			self.draft("arrear", "GRD H1")

	def test_another_colleges_coe_cannot_record_one(self):
		frappe.set_user(OTHER_COE)
		with self.assertRaises(frappe.PermissionError):
			self.draft("arrear", "GRD C4")

	def test_a_recognition_cannot_be_cancelled_once_the_student_completed(self):
		doc = self.recognise("arrear", "GRD C4")
		self.make_list()
		self.assertEqual(self.status("arrear"), "Award Eligible")
		with self.assertRaisesRegex(frappe.ValidationError, "can no longer be cancelled"):
			frappe.get_doc("Credit Recognition", doc.name).cancel()

	def test_mark_graduated_promotes_a_graduate_whose_hold_cleared(self):
		with owing(self.students["dist"]):
			doc = self.make_list(today())
		self.assertEqual(self.status("dist"), "Study Completed")
		self.assertEqual(convocation.graduate(doc.name), {"graduated": 5, "refused": []})
		self.assertEqual(self.status("dist"), "Graduated")

	def test_mark_graduated_runs_the_completion_check_again(self):
		doc = self.make_list(today())
		frappe.db.set_value("Student Result", {"student": self.students["dist"], "exam_session": self.s2}, "pending_ratification", 1)
		result = convocation.graduate(doc.name)
		self.assertEqual((result["graduated"], [r["student"] for r in result["refused"]]), (4, [self.students["dist"]]))
		self.assertIn("is Incomplete: Mandatory courses not cleared: GRD C3, GRD C4", result["refused"][0]["reason"])
		self.assertEqual(self.status("dist"), "Award Eligible")

	def test_the_authority_is_that_of_the_given_programme(self):
		self.assertIsNone(completion.award_refusal(self.students["dist"], today(), PROGRAM))
		self.assertIn("No Degree Awarding Authority is set for Grd Other BE", completion.award_refusal(self.students["dist"], today(), "Grd Other BE"))

	def test_the_authority_fits_the_awarding_body_and_is_kept_by_the_principal(self):
		authority = frappe.get_doc("Degree Awarding Authority", {"company": COLLEGE, "program": PROGRAM})
		authority.document_type, authority.document_authority = "Accreditation", "NIRF"
		with self.assertRaisesRegex(frappe.ValidationError, "needs Affiliation of University"):
			authority.save()
		frappe.set_user(COE_USER)
		self.assertFalse(frappe.has_permission("Degree Awarding Authority", "write", authority.name))
		self.assertTrue(frappe.has_permission("Degree Awarding Authority", "read", authority.name))
