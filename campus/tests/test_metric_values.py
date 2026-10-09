"""M01-02 / M01-03 (P3-T03) Metric Value: compute all, recompute rules, department rows, answers, overrides, access."""

import json
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from campus.campus_platform import bulk
from campus.campus_platform.approvals import approve, reject
from campus.iqac import api, compute, cycle as lifecycle, metric_values
from campus.iqac.setup import FRAMEWORK
from campus.tests.approval_fixtures import level, make_department
from campus.tests.factories import make_user
from campus.tests.test_accreditation_cycle import APPROVER, OWNER_A, OWNER_B
from campus.tests.test_iqac import COORDINATOR, FACULTY_USER, IqacFixture
from campus.tests.test_results import COLLEGE, PROGRAM

NODE_26_3, NODE_21_1 = f"{FRAMEWORK}-2.6.3", f"{FRAMEWORK}-2.1.1"
NARRATIVE_NODE, CHOICE_NODE, MANUAL_NODE = f"{FRAMEWORK}-1.1.1", f"{FRAMEWORK}-1.4.1", f"{FRAMEWORK}-2.2.2"
OTHER_CRITERION_NODE, NOT_DEPARTMENT_WISE = f"{FRAMEWORK}-3.2.1", f"{FRAMEWORK}-1.2.3"
POLICY = "IQAC Override Test Policy"


class TestRules(UnitTestCase):
	def test_effective_value_is_the_override_only_when_approved(self):
		effective = metric_values.effective_value
		self.assertEqual(effective(has_formula=True, computed=10, manual=7, override_approved=0), 10)
		self.assertEqual(effective(has_formula=True, computed=10, manual=7, override_approved=1), 7)
		self.assertEqual(effective(has_formula=True, computed=10, manual=0, override_approved=1), 0)  # an override to zero
		self.assertIsNone(effective(has_formula=True, computed=None, manual=7, override_approved=0))
		self.assertEqual(effective(has_formula=False, computed=None, manual=7, override_approved=0), 7)
		self.assertIsNone(effective(has_formula=False, computed=None, manual=None, override_approved=0))

	def test_word_count_ignores_markup_and_blank_space(self):
		count = metric_values.count_words
		self.assertEqual(count(None), 0)
		self.assertEqual(count("<p>One  two\nthree</p>"), 3)
		self.assertEqual(count("<div><b>Bold</b>&nbsp;text</div><p></p>"), 2)
		self.assertEqual(count("   "), 0)


class MetricFixture(IqacFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for user in (APPROVER, OWNER_A, OWNER_B):
			make_user(user, [COLLEGE])
		frappe.get_doc("User", APPROVER).add_roles("Principal")

	def setUp(self):
		super().setUp()
		frappe.db.delete("Approval Level", {"parenttype": "Approval Policy", "parent": ["in", self.policies()]})
		frappe.db.delete("Approval Policy", {"document_type": "Metric Override"})
		frappe.get_doc(
			{"doctype": "Approval Policy", "policy_name": POLICY, "document_type": "Metric Override",
			"levels": [level("User", APPROVER, title="IQAC")]}
		).insert()  # fmt: skip

	def policies(self):
		return frappe.get_all("Approval Policy", {"document_type": "Metric Override"}, pluck="name") or [""]

	def metric(self, node, department=None):
		code = node.rsplit("-", 1)[1]
		return frappe.get_doc("Metric Value", f"{self.cycle.name}-{code}" + (f"-{department}" if department else ""))

	def set_status(self, node, status):
		frappe.db.set_value("Metric Value", self.metric(node).name, "status", status)

	def override(self, node=NODE_26_3, proposed=50, reason="Hand count from the register"):
		return api.request_override(self.metric(node).name, proposed, reason)


class TestComputeAll(MetricFixture):
	def test_compute_fills_every_number_or_percent_node_with_a_formula(self):
		self.make_results()
		compute.compute_cycle(self.cycle.name)
		formula_nodes = frappe.get_all(
			"Framework Node",
			{"framework": FRAMEWORK, "formula": ["is", "set"], "answer_type": ["in", ["Number", "Percent"]]},
			pluck="code",
		)
		self.assertTrue(formula_nodes)
		for code in formula_nodes:
			values = frappe.get_all("Metric Value", {"cycle": self.cycle.name, "node": f"{FRAMEWORK}-{code}", "department": ["is", "not set"]},
				["computed_value", "value", "status", "computed_at"])  # fmt: skip
			self.assertEqual(len(values), 1, code)
			self.assertIsNotNone(values[0].computed_value, code)
			self.assertEqual(values[0].value, values[0].computed_value)
			self.assertEqual(values[0].status, "Computed")
			self.assertTrue(values[0].computed_at)

	def test_compute_all_queues_one_bulk_item_per_formula_node(self):
		with patch.object(bulk, "enqueue_run") as enqueue:
			run = api.compute_all(self.cycle.name)
		enqueue.assert_called_once_with(run)
		items = json.loads(frappe.db.get_value("Bulk Run", run, "items"))
		self.assertEqual(sorted(items), [NODE_21_1, NODE_26_3])
		self.assertEqual(frappe.db.get_value("Bulk Run", run, "run_type"), "IQAC Compute All")

	def test_the_bulk_handler_computes_its_node_for_the_cycle(self):
		self.make_results()
		run = frappe._dict(get_parameters=lambda: {"cycle": self.cycle.name})
		compute.compute_item(NODE_26_3, run)
		self.assertEqual(self.metric(NODE_26_3).computed_value, 66.67)
		self.assertFalse(frappe.db.exists("Metric Value", f"{self.cycle.name}-2.1.1"))

	def test_compute_all_is_refused_for_a_locked_cycle_and_without_the_role(self):
		frappe.set_user(FACULTY_USER)
		with self.assertRaises(frappe.PermissionError), patch.object(bulk, "enqueue_run"):
			api.compute_all(self.cycle.name)
		frappe.set_user("Administrator")
		frappe.db.set_value("Accreditation Cycle", self.cycle.name, "status", "Approved")
		with self.assertRaises(frappe.ValidationError), patch.object(bulk, "enqueue_run"):
			api.compute_all(self.cycle.name)


class TestDepartmentWise(MetricFixture):
	def test_department_wise_formulas_get_a_row_per_programme_department_and_a_company_row(self):
		department = make_department("Iqac Dept A", COLLEGE)
		other = make_department("Iqac Dept B", COLLEGE)
		frappe.db.set_value("Program", PROGRAM, "department", department)
		self.make_results()
		compute.compute_cycle(self.cycle.name)
		overall, dept_a = self.metric(NODE_21_1), self.metric(NODE_21_1, department)
		self.assertEqual(overall.value, 4)
		self.assertEqual(dept_a.value, 4)
		self.assertEqual(dept_a.department, department)
		self.assertFalse(frappe.db.exists("Metric Value", f"{self.cycle.name}-2.1.1-{other}"))  # no programme there
		records = json.loads(dept_a.snapshot)["inputs"]["students_admitted"]["records"]
		self.assertEqual(len(records), 4)
		self.assertEqual(self.metric(NODE_26_3, department).computed_value, 66.67)

	def test_a_department_row_needs_a_department_wise_node_of_the_cycles_company(self):
		department = make_department("Iqac Dept A", COLLEGE)
		foreign = make_department("Iqac Foreign Dept", "Iqac Other College")
		for node, dept in ((NOT_DEPARTMENT_WISE, department), (NODE_21_1, foreign)):
			with self.subTest(node=node), self.assertRaises(frappe.ValidationError):
				frappe.get_doc({"doctype": "Metric Value", "cycle": self.cycle.name, "node": node, "department": dept}).insert()


class TestRecomputeRules(MetricFixture):
	def change_data(self):
		"""Another final-year result appears: s_sa is lifted so the pass percentage moves."""
		frappe.db.set_value("Student Result Course", {"parent": f"SR-{self.session.name}-{self.s_ab.name}"}, "result", "Pass")

	def test_recompute_updates_a_computed_value(self):
		self.make_results()
		compute.compute_cycle(self.cycle.name)
		self.change_data()
		compute.compute_cycle(self.cycle.name)
		metric = self.metric(NODE_26_3)
		self.assertEqual(metric.computed_value, 100)
		self.assertEqual(metric.status, "Computed")
		self.assertFalse(metric.source_changed)

	def test_recompute_never_overwrites_a_verified_or_locked_value_but_says_the_source_changed(self):
		for status in ("Verified", "Locked"):
			with self.subTest(status=status):
				frappe.db.savepoint("recompute")
				self.make_results()
				compute.compute_cycle(self.cycle.name)
				self.set_status(NODE_26_3, status)
				before = self.metric(NODE_26_3)
				self.change_data()
				compute.compute_cycle(self.cycle.name)
				metric = self.metric(NODE_26_3)
				self.assertEqual(metric.status, status)
				self.assertEqual((metric.value, metric.computed_value, metric.snapshot), (before.value, 66.67, before.snapshot))
				self.assertTrue(metric.source_changed)
				self.assertEqual(metric.recomputed_value, 100)
				frappe.db.rollback(save_point="recompute")

	def test_recompute_with_unchanged_data_does_not_flag_a_verified_value(self):
		self.make_results()
		compute.compute_cycle(self.cycle.name)
		self.set_status(NODE_26_3, "Verified")
		compute.compute_cycle(self.cycle.name)
		self.assertFalse(self.metric(NODE_26_3).source_changed)

	def test_reopening_a_verified_value_lets_the_next_compute_refresh_it(self):
		self.make_results()
		compute.compute_cycle(self.cycle.name)
		name = self.metric(NODE_26_3).name
		api.verify_metric(name)
		self.change_data()
		compute.compute_cycle(self.cycle.name)
		self.assertTrue(self.metric(NODE_26_3).source_changed)
		api.reopen_metric(name)
		compute.compute_cycle(self.cycle.name)
		metric = self.metric(NODE_26_3)
		self.assertEqual((metric.computed_value, metric.status, metric.source_changed), (100, "Computed", 0))


class TestAnswers(MetricFixture):
	def make(self, node, **values):
		return frappe.get_doc({"doctype": "Metric Value", "cycle": self.cycle.name, "node": node, **values})

	def test_a_manual_number_is_the_effective_value_of_a_node_without_a_formula(self):
		metric = self.make(MANUAL_NODE, manual_value=18.5).insert()
		self.assertEqual((metric.value, metric.status, metric.answered), (18.5, "Draft", 1))

	def test_a_formula_node_does_not_take_a_manual_value_without_an_approved_override(self):
		self.make_results()
		compute.compute_cycle(self.cycle.name)
		metric = self.metric(NODE_26_3)
		metric.manual_value = 10
		with self.assertRaisesRegex(frappe.ValidationError, "(?i)override"):
			metric.save()
		self.assertEqual(self.metric(NODE_26_3).value, 66.67)

	def test_narrative_keeps_a_live_word_count_and_the_node_limit_is_left_to_validation(self):
		limit = frappe.db.get_value("Framework Node", NARRATIVE_NODE, "word_limit")
		text = "<p>" + " ".join(["word"] * (limit + 5)) + "</p>"
		metric = self.make(NARRATIVE_NODE, narrative=text).insert()
		self.assertEqual(metric.word_count, limit + 5)  # saved, so the pre-validation run (P3-T05) can flag it

	def test_choice_must_be_one_of_the_nodes_choices_and_answers_must_match_the_type(self):
		choices = frappe.db.get_value("Framework Node", CHOICE_NODE, "choices").splitlines()
		self.assertTrue(self.make(CHOICE_NODE, choice=choices[0]).insert().answered)
		for node, values in (
			(CHOICE_NODE, {"choice": "Not an option"}),
			(NARRATIVE_NODE, {"manual_value": 3}),
			(MANUAL_NODE, {"narrative": "text"}),
			(MANUAL_NODE, {"choice": "x"}),
		):
			with self.subTest(node=node, values=values), self.assertRaises(frappe.ValidationError):
				self.make(node, **values).insert()

	def test_a_metric_belongs_to_the_cycles_framework_and_is_unique_per_node(self):
		self.make(MANUAL_NODE, manual_value=1).insert()
		with self.assertRaises(frappe.DuplicateEntryError):
			self.make(MANUAL_NODE, manual_value=2).insert()
		with self.assertRaises(frappe.ValidationError):
			self.make("No Such Framework-1.1.1").insert()

	def test_verify_needs_an_answer_and_a_verified_answer_is_frozen_until_reopened(self):
		metric = self.make(MANUAL_NODE).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "answer"):
			api.verify_metric(metric.name)
		metric.manual_value = 12
		metric.save()
		api.verify_metric(metric.name)
		metric.reload()
		self.assertEqual((metric.status, metric.verified_by), ("Verified", frappe.session.user))
		metric.manual_value = 13
		with self.assertRaisesRegex(frappe.ValidationError, "Verified"):
			metric.save()
		api.reopen_metric(metric.name)
		metric.reload()
		metric.manual_value = 13
		metric.save()
		self.assertEqual((metric.value, metric.status), (13, "Draft"))

	def test_a_zero_is_an_answer_only_when_ticked(self):
		blank = self.make(MANUAL_NODE).insert()
		self.assertEqual(blank.answered, 0)
		blank.answered = 1
		blank.save()
		self.assertEqual((blank.answered, blank.value), (1, 0))
		api.verify_metric(blank.name)
		self.assertEqual(frappe.db.get_value("Metric Value", blank.name, "status"), "Verified")

	def test_prepare_values_makes_a_draft_row_for_each_node_to_answer_by_hand(self):
		names = lifecycle.prepare_values(self.cycle.name)
		self.assertIn(f"{self.cycle.name}-1.1.1", names)
		self.assertNotIn(f"{self.cycle.name}-2.6.3", names)  # computed, not answered by hand
		self.assertNotIn(f"{self.cycle.name}-2.6", names)  # key indicators carry no answer
		self.assertEqual(lifecycle.prepare_values(self.cycle.name), [])  # idempotent: nothing new
		self.assertEqual(self.metric(MANUAL_NODE).status, "Draft")


class TestOverrides(MetricFixture):
	def setUp(self):
		super().setUp()
		self.make_results()
		compute.compute_cycle(self.cycle.name)

	def decide(self, name, approver_action=approve, comment=None):
		request = frappe.db.get_value("Approval Request", {"reference_doctype": "Metric Override", "reference_name": name}, "name")
		frappe.set_user(APPROVER)
		try:
			approver_action(request, comment)
		finally:
			frappe.set_user("Administrator")

	def test_an_override_needs_a_reason(self):
		for reason in ("", "   ", None):
			with self.subTest(reason=reason), self.assertRaises(frappe.ValidationError):
				api.request_override(self.metric(NODE_26_3).name, 50, reason)

	def test_an_override_without_approval_keeps_the_computed_value_effective(self):
		name = self.override()
		metric = self.metric(NODE_26_3)
		self.assertEqual((metric.value, metric.manual_value, metric.override_approved), (66.67, 0, 0))  # pending
		self.decide(name, reject, "Evidence missing")
		metric = self.metric(NODE_26_3)
		self.assertEqual((metric.value, metric.override_approved), (66.67, 0))
		self.assertEqual(frappe.db.get_value("Metric Override", name, "docstatus"), 0)

	def test_an_approved_override_becomes_the_effective_value_with_its_reason(self):
		name = self.override(proposed=50)
		self.decide(name)
		metric = self.metric(NODE_26_3)
		self.assertEqual((metric.value, metric.computed_value, metric.manual_value), (50, 66.67, 50))
		self.assertEqual((metric.override_approved, metric.override_reason, metric.override_request),
			(1, "Hand count from the register", name))  # fmt: skip
		self.assertEqual(frappe.db.get_value("Metric Override", name, "docstatus"), 1)

	def test_recompute_keeps_the_approved_override_effective_and_refreshes_the_computed_value(self):
		self.decide(self.override(proposed=50))
		frappe.db.set_value("Student Result Course", {"parent": f"SR-{self.session.name}-{self.s_ab.name}"}, "result", "Pass")
		compute.compute_cycle(self.cycle.name)
		metric = self.metric(NODE_26_3)
		self.assertEqual((metric.value, metric.computed_value), (50, 100))

	def test_cancelling_an_approved_override_restores_the_computed_value(self):
		name = self.override(proposed=50)
		self.decide(name)
		frappe.get_doc("Metric Override", name).cancel()
		metric = self.metric(NODE_26_3)
		self.assertEqual((metric.value, metric.manual_value, metric.override_approved, metric.override_reason), (66.67, 0, 0, None))

	def test_the_requester_cannot_approve_and_nobody_submits_it_directly(self):
		name = self.override()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Metric Override", name).submit()  # a policy matches: only approval submits it
		with self.assertRaises(frappe.PermissionError):
			approve(frappe.db.get_value("Approval Request", {"reference_name": name}, "name"))

	def test_no_override_on_a_manual_a_verified_or_a_locked_value(self):
		manual = frappe.get_doc({"doctype": "Metric Value", "cycle": self.cycle.name, "node": MANUAL_NODE, "manual_value": 3}).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "formula"):
			api.request_override(manual.name, 4, "reason")
		for status in ("Verified", "Locked"):
			self.set_status(NODE_26_3, status)
			with self.subTest(status=status), self.assertRaisesRegex(frappe.ValidationError, status):
				self.override()

	def test_approval_after_the_value_was_locked_is_refused(self):
		name = self.override()
		self.set_status(NODE_26_3, "Locked")
		with self.assertRaises(frappe.ValidationError):
			self.decide(name)
		self.assertEqual(self.metric(NODE_26_3).value, 66.67)

	def test_request_override_is_for_the_iqac_role_or_the_criterion_owner(self):
		frappe.set_user(FACULTY_USER)
		with self.assertRaises(frappe.PermissionError):
			self.override()
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Accreditation Cycle", self.cycle.name)
		doc.append("owners", {"criterion": f"{FRAMEWORK}-2", "user": OWNER_A})
		doc.save()
		frappe.set_user(OWNER_A)
		self.assertTrue(self.override())  # the owner of criterion 2 asks for 2.6.3
		frappe.set_user(OWNER_B)
		with self.assertRaises(frappe.PermissionError):
			self.override()


class TestLockAndAccess(MetricFixture):
	def lock_cycle(self):
		frappe.db.set_value("Accreditation Cycle", self.cycle.name, "status", "Approved")
		lifecycle.lock_values(self.cycle.name)

	def test_a_locked_value_and_a_value_of_an_approved_cycle_cannot_change_or_be_made(self):
		lifecycle.prepare_values(self.cycle.name)
		self.lock_cycle()
		metric = self.metric(MANUAL_NODE)
		self.assertEqual(metric.status, "Locked")
		metric.manual_value = 5
		with self.assertRaisesRegex(frappe.ValidationError, "(?i)locked"):
			metric.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Metric Value", "cycle": self.cycle.name, "node": f"{FRAMEWORK}-2.3.3"}).insert()
		with self.assertRaises(frappe.ValidationError):
			api.verify_metric(metric.name)
		with self.assertRaises(frappe.ValidationError):
			api.reopen_metric(metric.name)

	def test_criterion_owners_edit_only_the_values_of_their_criteria(self):
		lifecycle.prepare_values(self.cycle.name)
		doc = frappe.get_doc("Accreditation Cycle", self.cycle.name)
		doc.append("owners", {"criterion": f"{FRAMEWORK}-2", "user": OWNER_A})
		doc.save()
		own, other = self.metric(MANUAL_NODE), self.metric(OTHER_CRITERION_NODE)
		frappe.set_user(OWNER_A)
		self.assertTrue(own.has_permission("write"))
		self.assertTrue(own.has_permission("read"))
		self.assertFalse(other.has_permission("write"))
		self.assertFalse(other.has_permission("read"))
		visible = frappe.get_list("Metric Value", {"cycle": self.cycle.name}, pluck="name")
		self.assertIn(own.name, visible)
		self.assertNotIn(other.name, visible)
		own.manual_value = 21
		own.save()
		self.assertEqual(self.metric(MANUAL_NODE).value, 21)

	def test_a_plain_user_and_another_college_see_no_metric_values(self):
		lifecycle.prepare_values(self.cycle.name)
		frappe.set_user(FACULTY_USER)
		self.assertFalse(self.metric(MANUAL_NODE).has_permission("read"))
		frappe.set_user(COORDINATOR)
		self.assertTrue(self.metric(MANUAL_NODE).has_permission("write"))
