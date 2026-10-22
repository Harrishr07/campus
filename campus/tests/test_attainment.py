"""P3-T10 integration tests (M03-03): Attainment Policy per regulation, the CO Attainment Run of an offering (released,
ratified results only; CO-tagged CIA and valuation question marks; k-anonymous closed-campaign survey scores), the PO
Attainment Run of a programme batch, the bulk-runner queueing, the input snapshot, policy isolation between
regulations, the reports and the NBA course-file print.

World: campus.tests.attainment_fixtures on the small demo; its docstring has the hand calculation.
"""

import json
from unittest.mock import patch

import frappe
from frappe.api.v1 import update_doc
from frappe.utils import add_days, today

from campus.curriculum import attainment
from campus.curriculum.attainment_rules import shown
from campus.curriculum.outcomes import validate_co_tags
from campus.curriculum.report.attainment_target_gap import attainment_target_gap
from campus.curriculum.report.co_attainment_by_course import co_attainment_by_course
from campus.curriculum.report.po_attainment_by_program import po_attainment_by_program
from campus.iqac import api as iqac_api
from campus.tests import attainment_fixtures as fx
from campus.tests.demo import ECE_DEPARTMENT, ENGINEERING, department_name, email
from campus.tests.factories import make_user
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

	def test_weights_add_up_to_100_within_a_hundredth(self):
		doc = frappe.get_doc("Attainment Policy", attainment.policy_for(self.r22))
		doc.update({"direct_weight": 80.005, "indirect_weight": 19.999})
		doc.save()

	def test_a_policy_a_submitted_run_used_is_locked_and_replaced_by_a_new_one(self):
		run = self.submitted_co_run()
		policy = frappe.get_doc("Attainment Policy", run.policy)
		policy.update({"direct_weight": 70, "indirect_weight": 30})
		with self.assertRaisesRegex(frappe.ValidationError, "locked"):
			policy.save()
		policy.reload()
		policy.disabled = 1
		policy.save()
		new = frappe.get_doc({"doctype": "Attainment Policy", "regulation": self.r22, **fx.POLICIES["R2022"], "direct_weight": 70, "indirect_weight": 30}).insert()
		self.assertEqual(attainment.policy_for(self.r22), new.name)
		self.assertEqual(frappe.db.get_value("CO Attainment Run", run.name, ["policy", "direct_weight"]), (policy.name, 80))


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
		run = self.co_run()
		snapshot = attainment.input_snapshot(run.name)
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
		self.assertEqual(snapshot["batches"], {fx.BATCH: 10})
		self.assertIn("raw valuation question marks", snapshot["ese_basis"])
		used = frappe.parse_json(run.questions_used)
		self.assertEqual(used["cos"]["CO3"], {"cia": ["CIA 2 Q2"], "ese": ["Q3", "Q4"]})
		self.assertNotIn("students", json.dumps(used))

	def test_only_released_sessions_count(self):
		frappe.db.set_value("Exam Session", fx.SESSION, "publish_at", add_days(today(), 3))  # embargoed
		doc = self.co_run()
		self.assertEqual(attainment.input_snapshot(doc.name)["students"], [])
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
		frappe.db.set_value("Attainment Policy", attainment.policy_for(self.r22), "direct_weight", 50)  # behind the lock
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
		run = snapshot["co_runs"][0]["name"]
		self.assertEqual(
			sorted(snapshot["cells"]["PO1"]),
			[["CO1", 2.4, 3, fx.course(), [[run, 2.4, 10]]], ["CO2", 1.87, 2, fx.course(), [[run, 1.87, 10]]]],
		)

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


class TestAttainmentAccess(AttainmentFixture):
	"""C1 / I1: per-student marks are read by System Manager, COE and Dean Academics only; a run is read by IQAC and COE
	college-wide, by the programme's HOD and the offering's instructors; only the programme's HOD (or the Dean) manages it."""

	OTHER_HOD = "att-ece-hod@example.com"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(cls.OTHER_HOD, [ENGINEERING])
		frappe.get_doc("User", cls.OTHER_HOD).add_roles("HOD", "Instructor")
		frappe.get_doc(
			{"doctype": "Position Holder", "position": "HOD", "scope_value": department_name(ECE_DEPARTMENT, ENGINEERING),
			"user": cls.OTHER_HOD, "from_date": add_days(today(), -30)}
		).insert(ignore_permissions=True)  # fmt: skip

	def setUp(self):
		super().setUp()
		self.run = self.co_run()

	def read_as(self, user, doctype="CO Attainment Run", name=None):
		frappe.set_user(user)
		try:
			return frappe.client.get(doctype, name or self.run.name)
		finally:
			frappe.set_user("Administrator")

	def listed_as(self, user, fields=("name", "questions_used")):
		frappe.set_user(user)
		try:
			return frappe.get_list("CO Attainment Run", fields=list(fields))
		finally:
			frappe.set_user("Administrator")

	def test_only_coe_dean_and_system_manager_read_the_per_student_snapshot(self):
		self.assertIn(S[0], self.read_as(email("coe"), "CO Attainment Snapshot")["snapshot"])
		self.assertNotIn("input_snapshot", frappe.get_meta("CO Attainment Run").get_valid_columns())
		for user in (email("iqac"), email("hod_cse"), email("faculty_1")):
			with self.assertRaises(frappe.PermissionError):
				self.read_as(user, "CO Attainment Snapshot")
			doc = self.read_as(user)
			self.assertNotIn(S[0], json.dumps(doc, default=str), user)
			self.assertTrue(doc.get("questions_used"), user)
			self.assertEqual(len(doc["results"]), 3, user)
			rows = self.listed_as(user)
			self.assertEqual([r.name for r in rows], [self.run.name], user)
			self.assertNotIn(S[0], json.dumps(rows, default=str), user)  # report view / export

	def test_the_hods_write_paths_return_no_student_marks(self):
		hod = email("hod_cse")
		frappe.set_user(hod)
		try:
			doc = frappe.get_doc("CO Attainment Run", self.run.name).as_dict()
			responses = {
				"save": frappe.client.save(doc),
				"set_value": frappe.client.set_value("CO Attainment Run", self.run.name, "course_offering", fx.OFFERING),
			}
			frappe.form_dict.data = "{}"
			responses["rest_put"] = update_doc("CO Attainment Run", self.run.name).as_dict()
			responses["submit"] = frappe.client.submit(frappe.get_doc("CO Attainment Run", self.run.name).as_dict())
			responses["cancel"] = frappe.client.cancel("CO Attainment Run", self.run.name) or frappe.get_doc("CO Attainment Run", self.run.name).as_dict()
		finally:
			frappe.form_dict.pop("data", None)
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("CO Attainment Run", self.run.name, "docstatus"), 2)
		for path, response in responses.items():
			text = json.dumps(response, default=str)
			self.assertTrue(text, path)
			for student in S[:10]:
				self.assertNotIn(student, text, path)
		self.assertIn(S[0], frappe.db.get_value("CO Attainment Snapshot", self.run.name, "snapshot"))  # kept apart

	def test_another_departments_hod_and_a_non_owning_instructor_cannot_read_the_run(self):
		for user in (self.OTHER_HOD, email("faculty_2")):
			with self.assertRaises(frappe.PermissionError):
				self.read_as(user)
			self.assertEqual(self.listed_as(user, ("name",)), [], user)

	def test_only_the_programmes_hod_or_the_dean_computes_and_submits(self):
		for user in (self.OTHER_HOD, email("faculty_1"), email("iqac")):
			frappe.set_user(user)
			try:
				with self.assertRaises(frappe.PermissionError):
					attainment.queue_co_run(self.run.name)
				with self.assertRaises(frappe.PermissionError):
					frappe.get_doc("CO Attainment Run", self.run.name).submit()
			finally:
				frappe.set_user("Administrator")
		frappe.set_user(self.OTHER_HOD)
		try:
			with self.assertRaisesRegex(frappe.ValidationError, "No offering"):  # the term's offerings are not their department's
				attainment.start_term_runs(ENGINEERING, self.world.term)
		finally:
			frappe.set_user("Administrator")
		frappe.set_user(email("hod_cse"))
		try:
			frappe.get_doc("CO Attainment Run", self.run.name).submit()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("CO Attainment Run", self.run.name, "docstatus"), 1)

	def test_a_po_run_is_the_programme_hods(self):
		po = frappe.get_doc({"doctype": "PO Attainment Run", "program": fx.PROGRAM, "batch": fx.BATCH}).insert()
		self.assertEqual(self.read_as(email("hod_cse"), "PO Attainment Run", po.name)["name"], po.name)
		self.assertEqual(self.read_as(email("iqac"), "PO Attainment Run", po.name)["name"], po.name)
		with self.assertRaises(frappe.PermissionError):
			self.read_as(self.OTHER_HOD, "PO Attainment Run", po.name)
		frappe.set_user(self.OTHER_HOD)
		try:
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc({"doctype": "PO Attainment Run", "program": fx.PROGRAM, "batch": fx.BATCH, "academic_year": fx.BATCH}).insert()
		finally:
			frappe.set_user("Administrator")


class TestInputGuards(AttainmentFixture):
	def test_untagged_ese_questions_flag_the_run_and_block_submit(self):  # I2
		frappe.db.set_value("Answer Script Bundle Question", {"parent": fx.BUNDLE}, "course_outcome", "")
		doc = self.co_run()
		self.assertTrue(doc.ese_untagged)
		self.assertEqual({r.ese_students for r in doc.results}, {0})
		with self.assertRaisesRegex(frappe.ValidationError, "CO tag"):
			doc.submit()

	def test_an_unanswered_choice_question_counts_in_neither_marks_nor_maximum(self):  # I3
		row = frappe.db.get_value("Curriculum Course", {"parent": fx.curriculum(), "course": fx.course()})
		frappe.db.set_value("Curriculum Course", row, {"exam_type": "Theory", "practical_periods": 0, "ese_max": 70})
		for idx, question in ((6, "Q6a"), (7, "Q6b")):  # either / or, CO1; the paper now adds up to 90 > 70
			frappe.get_doc({"doctype": "Answer Script Bundle Question", "parent": fx.BUNDLE, "parenttype": "Answer Script Bundle",
				"parentfield": "questions", "idx": idx, "question": question, "max_marks": 10, "course_outcome": "CO1"}).db_insert()  # fmt: skip
		for entry, mark in (("VE-ATT-1-1", 9), ("VE-ATT-1-2", 7)):  # s1 answered Q6a only
			frappe.get_doc({"doctype": "Valuation Entry Mark", "parent": entry, "parenttype": "Valuation Entry", "parentfield": "marks",
				"idx": 9, "question": "Q6a", "marks": mark}).db_insert()  # fmt: skip
		doc = self.co_run()
		self.assertTrue(doc.ese_choice_paper)
		ese = attainment.input_snapshot(doc.name)["cos"]["CO1"]["ese"]["students"]
		self.assertEqual(ese[S[0]], [22, 30, 1])  # Q1 14/20 + Q6a 8/10; Q6b left out
		self.assertEqual(ese[S[1]], [14, 20, 1])  # answered neither: both left out
		self.assertEqual(self.levels(doc)["CO1"][2], 55.56)

	def test_the_exit_survey_must_be_of_the_programme(self):  # I4
		for rule in (None, "ATT-AR-ECE"):
			if rule:
				fx.insert({"doctype": "Audience Rule", "name": rule, "rule_name": rule, "company": ENGINEERING,
					"rule_type": "Program and Semester", "program": "B.E. ECE"})  # fmt: skip
			frappe.db.set_value("Feedback Campaign", fx.EXIT_CAMPAIGN, "audience_rule", rule)
			with self.assertRaisesRegex(frappe.ValidationError, "exit survey of programme"):
				frappe.get_doc({"doctype": "PO Attainment Run", "program": fx.PROGRAM, "batch": fx.BATCH, "exit_survey": fx.EXIT_CAMPAIGN}).insert()

	def test_a_course_in_several_sections_weighs_once_in_a_po(self):  # I5
		run = self.submitted_co_run()
		section = run.as_dict()
		section.update({"name": "COAR-ATT-B", "course_offering": "ATT-DS-2022-B", "students": 30})
		section["results"] = [
			{**row, "name": frappe.generate_hash(length=10), "parent": "COAR-ATT-B", "final_level": 3, "assessed": 1} for row in section["results"]
		]
		fx.insert(section)
		rows = self.po_levels(self.po_run())
		self.assertEqual(rows["PO1"][0], 2.8)  # CO1 (2.4*10 + 3*30)/40 = 2.85, CO2 2.72: (2.85*3 + 2.72*2)/5
		self.assertEqual(rows["PO2"][0], 2.68)  # (2.72*3 + 2.55*1)/4
		self.assertEqual(rows["PO1"][4], 1)  # one course

	def test_a_failed_computation_leaves_the_run_failed_with_the_error(self):  # never stuck at Queued
		doc = frappe.get_doc({"doctype": "CO Attainment Run", "course_offering": fx.OFFERING}).insert()
		attainment.queue_co_runs([doc.name])
		frappe.db.delete("Course Outcome", {"course": fx.course(), "curriculum": fx.curriculum()})
		attainment.compute_co_item(doc.name)
		status, error = frappe.db.get_value("CO Attainment Run", doc.name, ["status", "error"])
		self.assertEqual(status, "Failed")
		self.assertIn("course outcomes", error)

	def test_po_run_lists_co_runs_without_a_matrix(self):
		run = self.submitted_co_run()
		frappe.db.set_value("CO Attainment Run", run.name, "matrix", None)
		po = self.po_run()
		self.assertIn(run.name, po.warnings)

	def test_a_term_skips_offerings_whose_policy_is_disabled(self):
		frappe.db.set_value("Attainment Policy", attainment.policy_for(self.r22), "disabled", 1)
		with self.assertRaisesRegex(frappe.ValidationError, "active Attainment Policy"):
			attainment.start_term_runs(ENGINEERING, self.world.term)

	def test_the_snapshot_survey_percent_uses_the_policy_scale(self):
		frappe.db.set_value("Attainment Policy", attainment.policy_for(self.r22), "survey_scale", 4)
		doc = self.co_run()
		self.assertEqual(attainment.input_snapshot(doc.name)["cos"]["CO2"]["indirect"]["percent"], 90)  # 3.6 of 4
		co2 = next(r for r in doc.results if r.co_code == "CO2")
		self.assertEqual((co2.indirect_percent, co2.indirect_level), (90, 2.7))
		self.assertIn("1-4", frappe.get_print("CO Attainment Run", doc.name, "Course Attainment Sheet"))
