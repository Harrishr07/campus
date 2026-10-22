"""M01-03 (P3-T05) Pre-validation: Validation Rules (data), the run per cycle with its results, the status gate, readiness report."""

import frappe
from frappe.tests import UnitTestCase

from campus.iqac import api, validation
from campus.iqac import cycle as lifecycle
from campus.iqac.report.cycle_readiness import cycle_readiness
from campus.iqac.setup import FRAMEWORK
from campus.tests import demo_slice
from campus.tests.test_evidence import EvidenceFixture
from campus.tests.test_iqac import COORDINATOR, FACULTY_USER

N212, EP41, N261 = f"{FRAMEWORK}-2.1.2", f"{FRAMEWORK}-EP-4.1", f"{FRAMEWORK}-4.1.1"
N263, CRITERION_2 = f"{FRAMEWORK}-2.6.3", f"{FRAMEWORK}-2"
SLOT = "Data Template"


class TestRuleLogic(UnitTestCase):
	def test_holds_covers_every_operator(self):
		for left, operator, right, expected in (
			(1, "<=", 1, True), (2, "<=", 1, False), (1, "<", 1, False), (0, "<", 1, True),
			(1, ">=", 1, True), (0, ">=", 1, False), (2, ">", 1, True), (1, ">", 1, False),
			(1, "=", 1, True), (1, "=", 2, False),
		):  # fmt: skip
			self.assertEqual(validation.holds(left, operator, right), expected, (left, operator, right))

	def test_outside_range_checks_each_bound_that_is_set(self):
		self.assertTrue(validation.outside_range(101, None, 100))
		self.assertFalse(validation.outside_range(100, None, 100))
		self.assertTrue(validation.outside_range(-1, 0, None))
		self.assertFalse(validation.outside_range(0, 0, None))
		self.assertFalse(validation.outside_range(5, None, None))
		self.assertTrue(validation.outside_range(5, 6, 9))

	def test_a_bound_must_be_a_finite_number(self):
		from campus.iqac.doctype.validation_rule.validation_rule import is_number

		for text in ("nan", "NaN", "inf", "-inf", "Infinity", "abc", ""):
			self.assertFalse(is_number(text), text)
		for text in ("0", "-1.5", "100", "1e3"):
			self.assertTrue(is_number(text), text)

	def test_the_range_text_shows_an_unset_bound_as_open_ended(self):
		self.assertEqual(validation.range_text("0", None), "0 or more")
		self.assertEqual(validation.range_text(None, "100"), "at most 100")
		self.assertEqual(validation.range_text("0", "100"), "0 to 100")

	def test_the_rule_type_options_are_the_ones_the_engine_checks(self):
		options = frappe.get_meta("Validation Rule").get_field("rule_type").options.split("\n")
		self.assertEqual(set(options), set(validation.CHECKS))


class ValidationFixture(EvidenceFixture):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Validation Rule", {"framework": FRAMEWORK})

	def rule(self, rule_type, node, **values):
		return frappe.get_doc(
			{"doctype": "Validation Rule", "framework": FRAMEWORK, "rule_type": rule_type, "node": node, "message": f"{rule_type} failed", **values}
		).insert()

	def answer(self, node, **values):
		return frappe.get_doc({"doctype": "Metric Value", "cycle": self.cycle.name, "node": node, **values}).insert()

	def failures(self, **match):
		return [row for row in validation.evaluate(self.cycle.name) if all(row.get(k) == v for k, v in match.items())]


class TestRuleRecord(ValidationFixture):
	def test_each_rule_type_needs_its_own_fields(self):
		with self.assertRaises(frappe.ValidationError):
			self.rule("Comparison", N212, operator="<=")  # no node to compare with
		with self.assertRaises(frappe.ValidationError):
			self.rule("Comparison", N212, compare_node=EP41)  # no operator
		with self.assertRaises(frappe.ValidationError):
			self.rule("Range", N212)  # neither bound
		with self.assertRaises(frappe.ValidationError):
			self.rule("Range", N212, minimum=9, maximum=1)
		with self.assertRaises(frappe.ValidationError):
			self.rule("Word Limit", N212)  # no limit anywhere: the node has none and the rule none
		self.assertTrue(self.rule("Word Limit", N261, limit=10).name)
		self.assertTrue(self.rule("Word Limit", N261).name)  # the node's own limit is used

	def test_the_node_must_belong_to_the_rules_framework(self):
		with self.assertRaises(frappe.ValidationError):
			self.rule("Non-empty", "No-such-node")

	def test_a_published_framework_still_takes_rules(self):
		self.assertEqual(frappe.db.get_value("Accreditation Framework", FRAMEWORK, "status"), "Published")
		self.assertTrue(self.rule("Non-empty", N212).name)


class TestEachRuleType(ValidationFixture):
	def test_required_evidence_fails_until_the_slot_is_filled(self):
		self.rule("Required Evidence", N263, slot_name=SLOT)
		[failure] = self.failures(rule_type="Required Evidence")
		self.assertEqual((failure.node, failure.severity), (N263, "Blocking"))
		self.make(nodes=[{"node": N263, "slot_name": SLOT}]).insert()
		self.assertEqual(self.failures(rule_type="Required Evidence"), [])

	def test_required_evidence_without_a_slot_name_checks_the_required_slots(self):
		self.rule("Required Evidence", N263)
		self.assertEqual(self.failures(rule_type="Required Evidence"), [])  # no slot of the node is marked required

	def test_word_limit_uses_the_rule_limit_then_the_node_limit(self):
		self.rule("Word Limit", N261, limit=3, severity="Warning")
		self.answer(N261, narrative="<p>one two three four five</p>")
		[failure] = self.failures(rule_type="Word Limit")
		self.assertIn("5", failure.detail)
		self.assertEqual(failure.severity, "Warning")

	def test_word_limit_falls_back_to_the_limit_of_the_node(self):
		self.rule("Word Limit", N261)
		limit = frappe.db.get_value("Framework Node", N261, "word_limit")
		self.answer(N261, narrative="<p>" + " ".join(["w"] * (limit + 1)) + "</p>")
		self.assertEqual(len(self.failures(rule_type="Word Limit")), 1)

	def test_word_limit_within_the_limit_passes(self):
		self.rule("Word Limit", N261, limit=5)
		self.answer(N261, narrative="<p>one two three four five</p>")
		self.assertEqual(self.failures(rule_type="Word Limit"), [])

	def test_comparison_flags_a_node_that_breaks_its_operator(self):
		self.rule("Comparison", N212, operator="<=", compare_node=EP41)
		self.answer(N212, manual_value=85)
		self.answer(EP41, manual_value=40)
		[failure] = self.failures(rule_type="Comparison")
		self.assertEqual(failure.node, N212)

	def test_comparison_passes_when_it_holds_and_is_skipped_while_a_side_is_unanswered(self):
		self.rule("Comparison", N212, operator="<=", compare_node=EP41)
		self.assertEqual(self.failures(rule_type="Comparison"), [])
		self.answer(N212, manual_value=30)
		self.assertEqual(self.failures(rule_type="Comparison"), [])
		self.answer(EP41, manual_value=40)
		self.assertEqual(self.failures(rule_type="Comparison"), [])

	def test_range_flags_a_value_outside_the_bounds(self):
		self.rule("Range", N212, minimum=0, maximum=100)
		self.answer(N212, manual_value=120)
		[failure] = self.failures(rule_type="Range")
		self.assertIn("120", failure.detail)

	def test_range_with_only_a_minimum_flags_values_below_it_and_names_no_missing_bound(self):
		self.rule("Range", N212, minimum=0)
		self.answer(N212, manual_value=-1)
		[failure] = self.failures(rule_type="Range")
		self.assertIn("0 or more", failure.detail)
		self.assertNotIn("None", failure.detail)

	def test_a_non_finite_bound_is_refused(self):
		for bound in ("nan", "inf"):
			with self.assertRaises(frappe.ValidationError):
				self.rule("Range", N212, minimum=bound)

	def test_range_passes_inside_the_bounds(self):
		self.rule("Range", N212, minimum=0, maximum=100)
		self.answer(N212, manual_value=100)
		self.assertEqual(self.failures(rule_type="Range"), [])

	def test_non_empty_fails_until_the_node_is_answered(self):
		self.rule("Non-empty", N212)
		self.assertEqual(len(self.failures(rule_type="Non-empty")), 1)
		self.answer(N212, manual_value=5)
		self.assertEqual(self.failures(rule_type="Non-empty"), [])

	def test_a_disabled_rule_is_not_checked(self):
		self.rule("Non-empty", N212, enabled=0)
		self.assertEqual(self.failures(), [])

	def test_rules_of_another_framework_are_not_checked(self):
		other = frappe.get_doc({"doctype": "Accreditation Framework", "framework_name": "VAL-OTHER-FW"}).insert()
		frappe.get_doc(
			{"doctype": "Framework Node", "framework": other.name, "code": "1", "title": "One", "node_type": "Criterion"}
		).insert()
		frappe.get_doc(
			{"doctype": "Validation Rule", "framework": other.name, "rule_type": "Non-empty", "node": f"{other.name}-1", "message": "x"}
		).insert()
		self.assertEqual(self.failures(), [])


class TestRunAndGate(ValidationFixture):
	def setUp(self):
		super().setUp()
		self.rule("Non-empty", N212, message="2.1.2 is empty")
		self.rule("Word Limit", N261, limit=2, severity="Warning", message="4.1.1 is too long")

	def blocked(self):
		self.cycle.reload()
		return self.cycle

	def test_a_run_lists_the_results_and_counts_by_severity(self):
		self.answer(N261, narrative="<p>a b c</p>")
		name = api.run_validation(self.cycle.name)
		run = frappe.get_doc("Validation Run", name)
		self.assertEqual((run.blocking, run.warnings), (1, 1))
		self.assertEqual({row.rule_type for row in run.results}, {"Non-empty", "Word Limit"})
		self.assertEqual(run.company, self.cycle.company)

	def test_a_cycle_with_a_blocking_failure_cannot_move_to_iqac_review(self):
		lifecycle.advance(self.cycle.name)
		with self.assertRaisesRegex(frappe.ValidationError, "2.1.2 is empty"):
			lifecycle.advance(self.cycle.name, comment="please")
		self.assertEqual(frappe.db.get_value("Accreditation Cycle", self.cycle.name, "status"), "Validating")

	def test_collecting_to_validating_is_not_gated(self):
		lifecycle.advance(self.cycle.name)
		self.assertEqual(frappe.db.get_value("Accreditation Cycle", self.cycle.name, "status"), "Validating")

	def test_warnings_need_a_comment_and_the_comment_is_kept(self):
		self.answer(N212, manual_value=5)
		self.answer(N261, narrative="<p>a b c</p>")
		lifecycle.advance(self.cycle.name)
		with self.assertRaisesRegex(frappe.ValidationError, "comment"):
			lifecycle.advance(self.cycle.name)
		lifecycle.advance(self.cycle.name, comment="Accepted by the IQAC")
		self.assertEqual(frappe.db.get_value("Accreditation Cycle", self.cycle.name, "status"), "IQAC Review")
		note = frappe.get_all(
			"Comment", {"reference_doctype": "Accreditation Cycle", "reference_name": self.cycle.name, "comment_type": "Comment"}, "content"
		)
		self.assertTrue(any("Accepted by the IQAC" in row.content and "1" in row.content for row in note))

	def test_a_clean_cycle_moves_without_a_comment(self):
		self.answer(N212, manual_value=5)
		lifecycle.advance(self.cycle.name)
		lifecycle.advance(self.cycle.name)
		self.assertEqual(frappe.db.get_value("Accreditation Cycle", self.cycle.name, "status"), "IQAC Review")

	def test_the_gate_checks_afresh_not_a_stale_run(self):
		self.answer(N212, manual_value=5)
		api.run_validation(self.cycle.name)
		frappe.db.set_value("Validation Rule", {"framework": FRAMEWORK, "rule_type": "Word Limit"}, "enabled", 0)
		self.rule("Range", N212, minimum=10, message="2.1.2 below 10")  # a new blocking rule after the run
		lifecycle.advance(self.cycle.name)
		with self.assertRaisesRegex(frappe.ValidationError, "below 10"):
			lifecycle.advance(self.cycle.name)

	def test_running_and_summary_need_the_iqac_role_and_the_cycles_company(self):
		frappe.set_user(FACULTY_USER)
		with self.assertRaises(frappe.PermissionError):
			api.run_validation(self.cycle.name)
		with self.assertRaises(frappe.PermissionError):
			api.validation_counts(self.cycle.name)
		frappe.set_user(COORDINATOR)
		self.assertEqual(api.validation_counts(self.cycle.name)["blocking"], 1)


class TestDemoProblems(ValidationFixture):
	def test_the_seeded_demo_flags_exactly_three_problems(self):
		demo_slice.seed_validation_problems(self.cycle.name)
		found = validation.evaluate(self.cycle.name)
		self.assertEqual(sorted((row.rule_type, row.node) for row in found), sorted([
			("Required Evidence", N263), ("Word Limit", N261), ("Comparison", N212),
		]))  # fmt: skip

	def test_seeding_twice_adds_no_rule(self):
		demo_slice.seed_validation_rules(FRAMEWORK)
		count = frappe.db.count("Validation Rule", {"framework": FRAMEWORK})
		demo_slice.seed_validation_rules(FRAMEWORK)
		self.assertEqual(frappe.db.count("Validation Rule", {"framework": FRAMEWORK}), count)


class TestReadinessReport(ValidationFixture):
	def rows(self, cycle=None):
		_, data = cycle_readiness.execute({"cycle": (cycle or self.cycle).name})
		return {row["criterion"]: row for row in data}

	def test_one_row_per_criterion_with_completion_failures_and_owner(self):
		self.rule("Non-empty", N212)
		self.rule("Required Evidence", N263, slot_name=SLOT, severity="Warning")
		self.answer(N261, narrative="<p>text</p>")
		self.cycle.append("owners", {"criterion": CRITERION_2, "user": COORDINATOR})
		self.cycle.save()
		rows = self.rows()
		two = rows[CRITERION_2]
		self.assertEqual((two["blocking"], two["warnings"], two["missing_evidence"]), (1, 1, 1))
		self.assertEqual(two["owner"], COORDINATOR)
		self.assertEqual(two["answered"], 0)
		self.assertEqual(two["completion"], 0)
		four = rows[f"{FRAMEWORK}-4"]
		self.assertEqual(four["answered"], 1)
		self.assertGreater(four["completion"], 0)

	def test_filling_evidence_clears_the_missing_count(self):
		self.rule("Required Evidence", N263, slot_name=SLOT)
		self.assertEqual(self.rows()[CRITERION_2]["missing_evidence"], 1)
		self.make(nodes=[{"node": N263, "slot_name": SLOT}]).insert()
		self.assertEqual(self.rows()[CRITERION_2]["missing_evidence"], 0)

	def test_a_user_outside_the_cycles_company_gets_nothing(self):
		from campus.tests.test_iqac import OTHER_COORDINATOR

		frappe.set_user(OTHER_COORDINATOR)
		with self.assertRaises(frappe.PermissionError):
			cycle_readiness.execute({"cycle": self.cycle.name})
