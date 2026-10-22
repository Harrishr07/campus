"""P3-T10 integration tests (M03-03): Attainment Policy per regulation, the CO Attainment Run of an offering (released,
ratified results only; CO-tagged CIA and valuation question marks; k-anonymous closed-campaign survey scores), the PO
Attainment Run of a programme batch, the bulk-runner queueing, the input snapshot, policy isolation between
regulations, the reports and the NBA course-file print.

World: campus.tests.attainment_fixtures on the small demo; its docstring has the hand calculation.
"""

import json
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from campus.curriculum import attainment
from campus.curriculum.attainment_rules import shown
from campus.curriculum.outcomes import validate_co_tags
from campus.curriculum.report.attainment_target_gap import attainment_target_gap
from campus.curriculum.report.co_attainment_by_course import co_attainment_by_course
from campus.curriculum.report.po_attainment_by_program import po_attainment_by_program
from campus.iqac import api as iqac_api
from campus.tests import attainment_fixtures as fx
from campus.tests.demo import ENGINEERING
from campus.tests.utils import CampusTestCase

S = fx.STUDENTS


class AttainmentFixture(CampusTestCase):
	demo_scale = "small"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.matrix = fx.seed_outcome_demo()
		cls.world = fx.make_assessment()
		cls.r22, cls.r26 = fx.regulation("R2022"), fx.regulation("R2026")

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("attainment_test")
		self.addCleanup(frappe.db.rollback, save_point="attainment_test")
		self.addCleanup(frappe.set_user, "Administrator")

	def co_run(self, offering=fx.OFFERING):
		doc = frappe.get_doc({"doctype": "CO Attainment Run", "course_offering": offering}).insert()
		attainment.compute_co_run(doc.name)
		return frappe.get_doc("CO Attainment Run", doc.name)

	def submitted_co_run(self):
		doc = self.co_run()
		doc.submit()
		return doc

	def levels(self, doc):
		fields = ("cia_percent", "cia_level", "ese_percent", "ese_level", "direct_level", "indirect_level", "final_level", "target_met")
		return {r.co_code: tuple(shown(r.as_dict())[f] for f in fields) for r in doc.results}

	def po_levels(self, doc):
		fields = ("direct_level", "indirect_level", "final_level", "target_met", "courses")
		return {r.outcome_code: tuple(shown(r.as_dict())[f] for f in fields) for r in doc.results}

	def po_run(self, exit_survey=fx.EXIT_CAMPAIGN, **values):
		doc = frappe.get_doc(
			{"doctype": "PO Attainment Run", "program": fx.PROGRAM, "batch": fx.BATCH, "exit_survey": exit_survey, **values}
		).insert()  # fmt: skip
		attainment.compute_po_run(doc.name)
		return frappe.get_doc("PO Attainment Run", doc.name)


class TestAttainmentPolicy(AttainmentFixture):
	def test_the_demo_seed_is_idempotent_and_approves_the_matrix(self):
		self.assertEqual(frappe.db.get_value("CO-PO Matrix", self.matrix, "docstatus"), 1)
		counts = [frappe.db.count(d) for d in ("Program Outcome", "Course Outcome", "Attainment Policy", "CO-PO Matrix")]
		self.assertEqual(fx.seed_outcome_demo(), self.matrix)
		self.assertEqual([frappe.db.count(d) for d in ("Program Outcome", "Course Outcome", "Attainment Policy", "CO-PO Matrix")], counts)

	def test_one_policy_per_regulation(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Attainment Policy", "regulation": self.r22, **fx.POLICIES["R2022"]}).insert()

	def test_weights_add_up_to_100(self):
		doc = frappe.get_doc("Attainment Policy", attainment.policy_for(self.r22))
		for field, value in (("indirect_weight", 30), ("ese_weight", 50)):
			doc.reload()
			doc.set(field, value)
			with self.assertRaisesRegex(frappe.ValidationError, "100"):
				doc.save()

	def test_bands_rise_with_the_level_and_the_target_is_reachable(self):
		doc = frappe.get_doc("Attainment Policy", attainment.policy_for(self.r22))
		doc.level_bands[1].min_students_percent = 70  # L2 above L3's 60
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.target_level = 4
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.append("level_bands", {"level": 3, "min_students_percent": 80})  # a level twice
		with self.assertRaises(frappe.ValidationError):
			doc.save()


class TestCOAttainmentRun(AttainmentFixture):
	def test_the_fixture_course_gives_the_hand_computed_co_levels(self):  # AC1
		doc = self.co_run()
		self.assertEqual(doc.status, "Computed")
		self.assertEqual((doc.policy, doc.regulation, doc.batch, doc.matrix), (attainment.policy_for(self.r22), self.r22, fx.BATCH, self.matrix))
		self.assertEqual((doc.direct_weight, doc.indirect_weight, doc.cia_weight, doc.ese_weight, doc.student_threshold), (80, 20, 40, 60, 60))
		self.assertEqual(
			self.levels(doc),
			{
				"CO1": (70, 3, 55.56, 2, 2.4, 2.4, 2.4, 1),
				"CO2": (60, 3, 44.44, 1, 1.8, 2.16, 1.87, 0),
				"CO3": (33.33, 0, 55.56, 2, 1.2, None, 1.2, 0),
			},
		)
		co3 = next(r for r in doc.results if r.co_code == "CO3")
		self.assertEqual((co3.cia_students, co3.cia_attained, co3.ese_students, co3.ese_attained), (9, 3, 9, 5))
		self.assertTrue(co3.indirect_suppressed)

	def test_the_snapshot_lists_the_questions_and_students_used_per_co(self):  # AC3
		snapshot = frappe.parse_json(self.co_run().input_snapshot)
		self.assertEqual(snapshot["exam_sessions"], [fx.SESSION])
		self.assertEqual(snapshot["students"], S[:10])  # SA and pending-ratification students left out
		co1, co3 = snapshot["cos"]["CO1"], snapshot["cos"]["CO3"]
		self.assertEqual(co1["cia"]["questions"], [{"question": "CIA 1 Q1", "max_marks": 10}])
		self.assertEqual(sorted(co1["cia"]["students"]), S[:10])
		self.assertEqual(co1["cia"]["students"][S[6]], [6, 10, 1])  # exactly 60 %: attains
		self.assertEqual(co1["ese"]["questions"], [{"question": "Q1", "max_marks": 20}])
		self.assertEqual(sorted(co1["ese"]["students"]), S[:9])  # s10 absent from the ESE
		self.assertEqual(co1["ese"]["students"][S[8]], [10, 20, 0])  # third valuation: rounds 2 and 3
		self.assertEqual([q["question"] for q in co3["ese"]["questions"]], ["Q3", "Q4"])
		self.assertNotIn(S[9], co3["cia"]["students"])  # absent from CIA 2 Q2
		self.assertEqual(snapshot["cos"]["CO2"]["indirect"], {"responses": 5, "average": 3.6, "percent": 72.0, "suppressed": 0})
		self.assertEqual(snapshot["policy"]["bands"], [[1, 40], [2, 50], [3, 60]])

	def test_only_released_sessions_count(self):
		frappe.db.set_value("Exam Session", fx.SESSION, "publish_at", add_days(today(), 3))  # embargoed
		doc = self.co_run()
		self.assertEqual(frappe.parse_json(doc.input_snapshot)["students"], [])
		self.assertEqual({r.assessed for r in doc.results}, {0})

	def test_a_draft_run_is_queued_on_the_bulk_runner(self):
		doc = frappe.get_doc({"doctype": "CO Attainment Run", "course_offering": fx.OFFERING}).insert()
		bulk_run = attainment.queue_co_runs([doc.name])
		self.assertEqual(json.loads(frappe.db.get_value("Bulk Run", bulk_run, "items")), [doc.name])
		self.assertEqual(frappe.db.get_value("Bulk Run", bulk_run, "handler"), attainment.CO_HANDLER)
		self.assertEqual(frappe.db.get_value("CO Attainment Run", doc.name, ["status", "bulk_run"]), ("Queued", bulk_run))

	def test_a_term_queues_a_run_per_offering_with_an_approved_matrix(self):
		bulk_run = attainment.start_term_runs(ENGINEERING, self.world.term)
		names = json.loads(frappe.db.get_value("Bulk Run", bulk_run, "items"))
		self.assertEqual([frappe.db.get_value("CO Attainment Run", n, "course_offering") for n in names], [fx.OFFERING])
		self.assertEqual(json.loads(frappe.db.get_value("Bulk Run", attainment.start_term_runs(ENGINEERING, self.world.term), "items")), names)

	def test_one_live_run_per_offering_and_submit_needs_a_computed_run(self):
		doc = frappe.get_doc({"doctype": "CO Attainment Run", "course_offering": fx.OFFERING}).insert()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "CO Attainment Run", "course_offering": fx.OFFERING}).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "Compute"):
			doc.submit()

	def test_an_offering_without_a_curriculum_or_policy_is_refused(self):
		frappe.db.delete("Attainment Policy", {"regulation": self.r22})
		with self.assertRaisesRegex(frappe.ValidationError, "Attainment Policy"):
			frappe.get_doc({"doctype": "CO Attainment Run", "course_offering": fx.OFFERING}).insert()


class TestPolicyIsolation(AttainmentFixture):
	def test_changing_the_r2026_policy_does_not_change_r2022_batch_results(self):  # AC2
		doc = self.co_run()
		before = self.levels(doc)
		r26 = frappe.get_doc("Attainment Policy", attainment.policy_for(self.r26))
		r26.update({"direct_weight": 50, "indirect_weight": 50, "student_threshold": 90, "po_indirect_weight": 50})
		r26.save()
		attainment.compute_co_run(doc.name)
		doc = frappe.get_doc("CO Attainment Run", doc.name)
		self.assertEqual(self.levels(doc), before)
		doc.submit()
		po = self.po_run()
		self.assertEqual(po.po_indirect_weight, 20)
		self.assertEqual({r.outcome_code: r.final_level for r in po.results if r.mapped}, {"PO1": 2.28, "PO2": 1.7, "PSO1": 1.2})

	def test_a_submitted_run_keeps_the_policy_it_was_computed_with(self):
		doc = self.submitted_co_run()
		before = self.levels(doc)
		frappe.db.set_value("Attainment Policy", attainment.policy_for(self.r22), "direct_weight", 50)
		self.assertEqual(self.levels(frappe.get_doc("CO Attainment Run", doc.name)), before)
		self.assertEqual(frappe.db.get_value("CO Attainment Run", doc.name, "direct_weight"), 80)

	def test_an_r2026_offering_uses_the_r2026_policy(self):
		c26 = frappe.get_doc(
			{"doctype": "Curriculum", "program": fx.PROGRAM, "regulation": self.r26, "status": "Draft",
			"courses": [{"semester": 2, "course": fx.course(), "category": "PCC", "lecture_periods": 3}]}
		).insert().name  # fmt: skip
		fx.insert({"doctype": "Student Group", "name": "ATT-DS-2026-A", "student_group_name": "ATT-DS-2026-A", "group_based_on": "Course",
			"academic_year": fx.BATCH, "academic_term": self.world.term, "program": fx.PROGRAM, "course": fx.course(),
			"oc_company": ENGINEERING, "oc_curriculum": c26})  # fmt: skip
		doc = frappe.get_doc({"doctype": "CO Attainment Run", "course_offering": "ATT-DS-2026-A"}).insert()
		self.assertEqual((doc.regulation, doc.policy), (self.r26, attainment.policy_for(self.r26)))


class TestPOAttainmentRun(AttainmentFixture):
	def test_the_fixture_batch_gives_the_hand_computed_po_levels(self):  # AC1
		self.submitted_co_run()
		doc = self.po_run()
		self.assertEqual((doc.regulation, doc.policy, doc.po_indirect_weight), (self.r22, attainment.policy_for(self.r22), 20))
		rows = self.po_levels(doc)
		self.assertEqual(rows["PO1"], (2.19, 2.64, 2.28, 1, 1))
		self.assertEqual(rows["PO2"], (1.7, None, 1.7, 0, 1))
		self.assertEqual(rows["PSO1"], (1.2, None, 1.2, 0, 1))
		self.assertEqual(rows["PO3"], (None, None, None, 0, 0))
		self.assertEqual(len(rows), 14)
		snapshot = frappe.parse_json(doc.input_snapshot)
		self.assertEqual([r["course_offering"] for r in snapshot["co_runs"]], [fx.OFFERING])
		self.assertEqual(sorted(snapshot["cells"]["PO1"]), sorted([["CO1", 2.4, 3, snapshot["co_runs"][0]["name"]], ["CO2", 1.87, 2, snapshot["co_runs"][0]["name"]]]))

	def test_draft_co_runs_and_other_years_do_not_count(self):
		doc = self.co_run()  # computed, not submitted
		self.assertIsNone(self.po1(self.po_run()))
		doc.submit()
		self.assertIsNone(self.po1(self.po_run(academic_year=fx.year_name(2023))))
		self.assertEqual(self.po1(self.po_run(academic_year=fx.BATCH)), 2.28)

	def test_one_live_po_run_per_program_batch_and_year(self):
		self.po_run()
		with self.assertRaises(frappe.ValidationError):
			self.po_run()

	def po1(self, doc):
		return self.po_levels(doc)["PO1"][2]

	def test_the_exit_survey_must_be_a_closed_campaign_of_the_college(self):
		frappe.db.set_value("Feedback Campaign", fx.EXIT_CAMPAIGN, "end_date", add_days(today(), 5))
		with self.assertRaisesRegex(frappe.ValidationError, "closed"):
			frappe.get_doc({"doctype": "PO Attainment Run", "program": fx.PROGRAM, "batch": fx.BATCH, "exit_survey": fx.EXIT_CAMPAIGN}).insert()

	def test_exit_survey_scores_hide_small_groups(self):
		scores = iqac_api.campaign_outcome_scores(fx.EXIT_CAMPAIGN)
		self.assertEqual(scores["PO1"], {"responses": 5, "average": 4.4, "percent": 88.0, "suppressed": 0})
		self.assertEqual(scores["PO2"]["suppressed"], 1)
		self.assertIsNone(scores["PO2"]["average"])

	def test_a_po_run_is_queued_on_the_bulk_runner(self):
		doc = frappe.get_doc({"doctype": "PO Attainment Run", "program": fx.PROGRAM, "batch": fx.BATCH}).insert()
		bulk_run = attainment.queue_po_run(doc.name)
		self.assertEqual(json.loads(frappe.db.get_value("Bulk Run", bulk_run, "items")), [doc.name])
		self.assertEqual(frappe.db.get_value("PO Attainment Run", doc.name, "status"), "Queued")


class TestAttainmentReports(AttainmentFixture):
	def setUp(self):
		super().setUp()
		self.co = self.submitted_co_run()
		self.po = self.po_run()
		self.po.submit()

	def test_co_attainment_by_course_and_faculty(self):
		columns, rows = co_attainment_by_course.execute({"company": ENGINEERING, "instructor": self.world.instructor})[:2]
		self.assertEqual([(r["course_offering"], r["co_code"], r["final_level"], r["gap"]) for r in rows],
			[(fx.OFFERING, "CO1", 2.4, None), (fx.OFFERING, "CO2", 1.87, 0.13), (fx.OFFERING, "CO3", 1.2, 0.8)])  # fmt: skip
		self.assertIn(self.world.instructor, rows[0]["instructors"])
		self.assertEqual(co_attainment_by_course.execute({"company": ENGINEERING, "instructor": "nobody"})[1], [])

	def test_po_attainment_by_program_and_batch(self):
		rows = po_attainment_by_program.execute({"company": ENGINEERING, "program": fx.PROGRAM, "batch": fx.BATCH})[1]
		self.assertEqual({r["outcome_code"]: r["final_level"] for r in rows if r["final_level"] is not None}, {"PO1": 2.28, "PO2": 1.7, "PSO1": 1.2})

	def test_target_gap_lists_the_outcomes_below_target(self):
		rows = attainment_target_gap.execute({"company": ENGINEERING})[1]
		self.assertEqual([(r["level"], r["outcome_code"], r["gap"]) for r in rows],
			[("CO", "CO2", 0.13), ("CO", "CO3", 0.8), ("PO", "PO2", 0.3), ("PO", "PSO1", 0.8)])  # fmt: skip

	def test_reports_are_for_permitted_colleges(self):
		scope = "campus.curriculum.attainment.permitted_companies"
		with patch(scope, return_value=["Some Other College"]):
			for report in (co_attainment_by_course, po_attainment_by_program, attainment_target_gap):
				with self.assertRaises(frappe.PermissionError):
					report.execute({"company": ENGINEERING})

	def test_nba_course_file_print(self):
		html = frappe.get_print("CO Attainment Run", self.co.name, "Course Attainment Sheet")
		for text in ("CO1", "2.4", "1.87", "CIA 1 Q1", "80", fx.OFFERING):
			self.assertIn(text, html)


class TestCOTags(AttainmentFixture):
	def test_valuation_question_tags_are_cos_of_the_course(self):
		bundle = frappe.get_doc("Answer Script Bundle", fx.BUNDLE)
		bundle.questions[0].course_outcome = "co9"
		with self.assertRaisesRegex(frappe.ValidationError, "CO9"):
			validate_co_tags(bundle)
		bundle.questions[0].course_outcome = "co2"
		validate_co_tags(bundle)
		self.assertEqual(bundle.questions[0].course_outcome, "CO2")

	def test_an_unchanged_legacy_tag_does_not_block_an_unrelated_save(self):
		frappe.db.set_value("Answer Script Bundle Question", {"parent": fx.BUNDLE, "question": "Q1"}, "course_outcome", "CO1, CO2")
		bundle = frappe.get_doc("Answer Script Bundle", fx.BUNDLE)
		bundle._doc_before_save = frappe.get_doc("Answer Script Bundle", fx.BUNDLE)
		validate_co_tags(bundle)  # unchanged: left alone
		self.assertEqual(bundle.questions[0].course_outcome, "CO1, CO2")
		bundle.questions[0].course_outcome = "CO1, CO3"
		with self.assertRaises(frappe.ValidationError):
			validate_co_tags(bundle)
