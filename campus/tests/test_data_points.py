"""M01-02 tests: Data Point registry sync, formula sandbox, node references with cycle detection, snapshot format."""

import json
from unittest.mock import patch

import frappe

from campus.iqac import compute, framework
from campus.iqac.formula import ENGINE_VERSION, evaluate, node_identifier
from campus.iqac.registry import REGISTRY, data_point_keys
from campus.iqac.setup import sync_data_points
from campus.tests.factories import make_company
from campus.tests.utils import CampusTestCase

REFUSALS = (SyntaxError, NameError, TypeError, ValueError, RecursionError, MemoryError)
SCRATCH = "DP Scratch Framework"
PHASE_1_2_KEYS = {
	"students_admitted", "final_year_appeared", "final_year_passed", "scholarship_govt_students",
	"scholarship_inst_students", "reserved_seats_filled", "seats_earmarked_reserved", "total_students",
	"outgoing_students", "programmes_offered", "courses_offered", "mentor_ratio", "full_time_teachers",
	"sanctioned_posts", "phd_teachers", "teacher_experience_years", "student_teacher_ratio", "fdp_teachers",
	"teachers_financially_supported", "syllabus_revised_programmes", "new_courses_introduced", "evaluation_grievances",
	"days_exam_to_result", "students_appeared", "pass_percentage",
}  # fmt: skip
ESCAPES = [
	"__import__('os').getcwd()",
	"().__class__.__base__.__subclasses__()",
	"().__class__.__bases__[0].__subclasses__()",
	"frappe.db.get_value('User', 'Administrator', 'name')",
	"frappe.session.user",
	"getattr(students_admitted, 'real')",
	"students_admitted.real",
	"(lambda: 1)()",
	"(lambda x: x)(students_admitted)",
	"[c for c in ().__class__.__mro__]",
	"[x for x in (1, 2)]",
	"[round for _ in (1,)]",
	"{k: v for k, v in globals().items()}",
	"list(x for x in (1,))",
	"[g for g in (lambda: 1).__globals__]",
	"open('/etc/passwd')",
	"eval('1')",
	"exec('x = 1')",
	"globals()",
	"vars()",
	"dir()",
	"type(1)",
	"compile('1', 'x', 'eval')",
	"round(*(1, 2))",
	"max(*students_admitted)",
	"__builtins__",
	"__builtins__['open']",
	"f'{students_admitted}'",
	"f'{9 ** 9}'",
	"-" * 5000 + "1",
	"(" * 300 + "1" + ")" * 300,
	"1 + " * 5000 + "1",
	"1" * 2000,
	"'{0.__class__}'.format(1)",
	"'a' * 10",
	"students_admitted if open else 1",
	"9 ** 9 ** 9",
	"(x := 1)",
	"students_admitted[0]",
]


def make_scratch():
	"""A Draft framework with a criterion, a key indicator and three metrics (no formulas yet)."""
	frappe.get_doc({"doctype": "Accreditation Framework", "framework_name": SCRATCH, "version": "1"}).insert()
	for code, node_type, parent in (("9", "Criterion", None), ("9.9", "Key Indicator", "9")):
		node(code, node_type, parent=parent and f"{SCRATCH}-{parent}").insert()
	return SCRATCH


def node(code, node_type="Metric", formula=None, parent=f"{SCRATCH}-9.9", framework_name=SCRATCH):
	values = {
		"doctype": "Framework Node", "framework": framework_name, "code": code, "title": f"t{code}",
		"node_type": node_type, "parent_node": parent, "formula": formula,
	}  # fmt: skip
	if node_type == "Metric":
		values.update(answer_type="Number", unit="n")
	return frappe.get_doc(values)


class ScratchCase(CampusTestCase):
	"""Each test starts and ends at a savepoint, so the scratch framework is rebuilt per test."""

	def setUp(self):
		super().setUp()
		frappe.db.savepoint("dp_test")
		self.addCleanup(frappe.db.rollback, save_point="dp_test")


class TestDataPointRegistrySync(CampusTestCase):
	def test_every_registered_metric_is_a_data_point_after_sync(self):
		keys = data_point_keys()
		sync_data_points()
		self.assertEqual(set(frappe.get_all("Data Point", pluck="name")), keys)
		self.assertTrue(PHASE_1_2_KEYS <= keys)

	def test_data_point_describes_its_function(self):
		sync_data_points()
		point = frappe.get_doc("Data Point", "students_admitted")
		self.assertEqual(point.key, "students_admitted")
		self.assertEqual(point.module, "Admissions")
		self.assertEqual(point.parameters, "company, academic_year, department")
		self.assertEqual(point.function, "campus.iqac.datapoints.students_admitted")
		self.assertTrue(point.description)
		for name in frappe.get_all("Data Point", pluck="name"):
			module, description = frappe.db.get_value("Data Point", name, ["module", "description"])
			self.assertTrue(module and description, name)

	def test_sync_is_idempotent_and_removes_data_points_no_longer_registered(self):
		sync_data_points()
		frappe.get_doc(
			{"doctype": "Data Point", "key": "zz_retired", "module": "IQAC", "description": "gone"}
		).insert(ignore_permissions=True)
		sync_data_points()
		sync_data_points()
		self.assertFalse(frappe.db.exists("Data Point", "zz_retired"))
		self.assertEqual(len(frappe.get_all("Data Point")), len(REGISTRY))

	def test_data_points_are_read_only_for_users(self):
		sync_data_points()
		permissions = frappe.get_meta("Data Point").permissions
		self.assertTrue(permissions)
		self.assertFalse(any(p.write or p.create or p.delete for p in permissions))


class TestFormulaSandbox(ScratchCase):
	def test_escapes_cannot_be_evaluated(self):
		for formula in ESCAPES:
			with self.subTest(formula=formula), self.assertRaises(REFUSALS):
				evaluate(formula, {"students_admitted": 1})

	def test_escapes_fail_validation_on_save(self):
		make_scratch()
		for formula in ESCAPES:
			with self.subTest(formula=formula), self.assertRaises(frappe.ValidationError):
				node("9.9.1", formula=formula).insert()

	def test_bare_function_is_not_a_numeric_result(self):
		make_scratch()
		for formula in ("round", "max", "min + 1"):
			with self.subTest(formula=formula), self.assertRaises(frappe.ValidationError):
				node("9.9.1", formula=formula).insert()

	def test_whitelisted_namespace_still_evaluates(self):
		self.assertEqual(evaluate("round(total_students / full_time_teachers, 2)", {"total_students": 10, "full_time_teachers": 4}), 2.5)
		self.assertEqual(evaluate("max(a, b) - min(a, b)", {"a": 7, "b": 2}), 5)
		self.assertEqual(evaluate("a if a > b else b", {"a": 1, "b": 2}), 2)
		self.assertEqual(evaluate("a > 0 and b > 0", {"a": 1, "b": 2}), True)
		self.assertEqual(evaluate("-a + 1.5", {"a": 1}), 0.5)

	def test_names_outside_the_given_values_are_undefined(self):
		with self.assertRaises(NameError):
			evaluate("final_year_passed", {"students_admitted": 1})


class TestNodeReferences(ScratchCase):
	def setUp(self):
		super().setUp()
		make_scratch()

	def test_node_identifier_is_a_python_name_built_from_the_code(self):
		self.assertEqual(node_identifier("2.6.3"), "n_2_6_3")
		self.assertEqual(node_identifier("EP-3.1"), "n_EP_3_1")

	def test_unknown_data_point_and_unknown_node_fail_validation(self):
		for formula in ("students_admitted + not_a_point", "n_9_9_77 + 1", "n_8_8_1"):
			with self.subTest(formula=formula), self.assertRaises(frappe.ValidationError):
				node("9.9.1", formula=formula).insert()

	def test_a_node_formula_may_use_data_points_and_other_node_formulas(self):
		node("9.9.1", formula="round(total_students / full_time_teachers, 2)").insert()
		self.assertTrue(node("9.9.2", formula="n_9_9_1 * 2 + students_admitted").insert())

	def test_reference_to_a_node_without_a_formula_fails(self):
		node("9.9.1").insert()
		with self.assertRaises(frappe.ValidationError):
			node("9.9.2", formula="n_9_9_1 + 1").insert()

	def test_self_reference_is_a_cycle(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			node("9.9.1", formula="n_9_9_1 + 1").insert()
		self.assertIn("cycl", str(caught.exception).lower())

	def test_two_node_and_three_node_cycles_fail_on_save(self):
		a = node("9.9.1", formula="students_admitted").insert()
		node("9.9.2", formula="n_9_9_1 + 1").insert()
		node("9.9.3", formula="n_9_9_2 + 1").insert()
		a.formula = "n_9_9_3 + 1"
		with self.assertRaises(frappe.ValidationError) as caught:
			a.save()
		self.assertIn("9.9.1", str(caught.exception))
		a.reload()
		self.assertEqual(a.formula, "students_admitted")

	def test_a_diamond_is_not_a_cycle(self):
		node("9.9.1", formula="students_admitted").insert()
		node("9.9.2", formula="n_9_9_1 + 1").insert()
		node("9.9.3", formula="n_9_9_1 + 2").insert()
		self.assertTrue(node("9.9.4", formula="n_9_9_2 + n_9_9_3").insert())

	def test_a_referenced_formula_cannot_be_cleared_or_the_node_deleted(self):
		a = node("9.9.1", formula="students_admitted").insert()
		node("9.9.2", formula="n_9_9_1 + 1").insert()
		a.formula = None
		with self.assertRaises(frappe.ValidationError):
			a.save()
		a.reload()
		with self.assertRaises(frappe.ValidationError):
			a.delete()

	def test_clone_keeps_node_references_whatever_the_creation_order(self):
		node("9.9.2", formula="students_admitted").insert()
		node("9.9.1", formula="n_9_9_2 + 1").insert()  # 9.9.1 is created before 9.9.2 in a clone
		frappe.db.set_value("Accreditation Framework", SCRATCH, "status", "Published")
		clone = framework.clone(SCRATCH, "DP Scratch Clone", "2")
		self.assertEqual(frappe.db.get_value("Framework Node", f"{clone}-9.9.1", "formula"), "n_9_9_2 + 1")


class TestSyncKeepsUsedDataPoints(ScratchCase):
	def test_a_data_point_used_by_a_formula_is_kept_flagged_unregistered_not_deleted(self):
		sync_data_points()
		make_scratch()
		node("9.9.1", formula="students_admitted * 2").insert()
		frappe.get_doc(
			{"doctype": "Data Point", "key": "zz_gone", "module": "IQAC", "description": "x", "registered": 1}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Framework Node", f"{SCRATCH}-9.9.1", "formula", "students_admitted + zz_gone")
		with patch("campus.iqac.setup.frappe.log_error"):
			sync_data_points()
		self.assertEqual(frappe.db.get_value("Data Point", "zz_gone", "registered"), 0)
		self.assertEqual(frappe.db.get_value("Data Point", "students_admitted", "registered"), 1)
		frappe.db.set_value("Framework Node", f"{SCRATCH}-9.9.1", "formula", "students_admitted")
		sync_data_points()
		self.assertFalse(frappe.db.exists("Data Point", "zz_gone"))


class TestComputeSnapshot(ScratchCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = make_company("DP College", "DPC")

	def setUp(self):
		super().setUp()
		make_scratch()
		node("9.9.1", formula="round(total_students / full_time_teachers, 2)").insert()
		node("9.9.2", formula="n_9_9_1 * 2").insert()
		frappe.db.set_value("Accreditation Framework", SCRATCH, "status", "Published")
		year = frappe.get_all("Academic Year", pluck="name", limit=1)[0]
		self.cycle = frappe.get_doc(
			{"doctype": "Accreditation Cycle", "framework": SCRATCH, "company": "DP College", "academic_year": year}
		).insert()

	def points(self, teachers=4):
		rows = {
			"total_students": {"value": 100, "records": [{"doctype": "Student", "name": "S1"}]},
			"full_time_teachers": {"value": teachers, "records": [{"doctype": "Employee", "name": "E1"}]},
		}
		return patch.object(compute, "data_point", side_effect=lambda key, *args: rows[key])

	def test_snapshot_has_inputs_formula_result_computed_at_and_engine_version(self):
		with self.points():
			name = compute.compute_node(self.cycle, f"{SCRATCH}-9.9.1")
		metric = frappe.get_doc("Metric Value", name)
		snapshot = json.loads(metric.snapshot)
		self.assertEqual(set(snapshot), {"inputs", "formula", "result", "computed_at", "engine_version"})
		self.assertEqual(snapshot["formula"], "round(total_students / full_time_teachers, 2)")
		self.assertEqual(snapshot["result"], 25)
		self.assertEqual(snapshot["engine_version"], ENGINE_VERSION)
		self.assertEqual(snapshot["inputs"]["total_students"]["value"], 100)
		self.assertEqual(snapshot["inputs"]["total_students"]["records"], [{"doctype": "Student", "name": "S1"}])
		self.assertEqual(metric.value, 25)

	def test_node_reference_input_carries_the_referenced_metric_value(self):
		with self.points():
			name = compute.compute_node(self.cycle, f"{SCRATCH}-9.9.2")
		snapshot = json.loads(frappe.db.get_value("Metric Value", name, "snapshot"))
		upstream = f"{self.cycle.name}-9.9.1"
		self.assertEqual(snapshot["result"], 50)
		self.assertEqual(snapshot["inputs"]["n_9_9_1"], {"value": 25, "records": [{"doctype": "Metric Value", "name": upstream}]})
		self.assertTrue(frappe.db.exists("Metric Value", upstream))

	def test_compute_cycle_computes_each_node_once_in_dependency_order(self):
		with self.points() as points:
			names = compute.compute_cycle(self.cycle.name)
		self.assertEqual(sorted(names), [f"{self.cycle.name}-9.9.1", f"{self.cycle.name}-9.9.2"])
		self.assertEqual(points.call_count, 2)  # total_students and full_time_teachers, once

	def test_one_bad_node_does_not_abort_the_cycle(self):
		frappe.db.set_value("Accreditation Framework", SCRATCH, "status", "Draft")
		node("9.9.3", formula="students_admitted").insert()
		frappe.db.set_value("Accreditation Framework", SCRATCH, "status", "Published")
		frappe.db.set_value("Framework Node", f"{SCRATCH}-9.9.3", "formula", "not_a_point + 1")
		with self.points(), patch("campus.iqac.compute.frappe.log_error") as log:
			names = compute.compute_cycle(self.cycle.name)
		self.assertEqual(sorted(names), [f"{self.cycle.name}-9.9.1", f"{self.cycle.name}-9.9.2"])
		self.assertTrue(log.called)

	def test_no_denominator_gives_zero_through_a_chain(self):
		with self.points(teachers=0):
			name = compute.compute_node(self.cycle, f"{SCRATCH}-9.9.2")
		self.assertEqual(frappe.db.get_value("Metric Value", name, "value"), 0)


class TestFrameworkCarryOver(ScratchCase):
	def test_a_cycle_needs_a_published_framework(self):
		make_scratch()
		node("9.9.1", formula="students_admitted").insert()
		make_company("DP College Two", "DPT")
		company = "DP College Two"
		year = frappe.get_all("Academic Year", pluck="name", limit=1)[0]
		cycle = {"doctype": "Accreditation Cycle", "framework": SCRATCH, "company": company, "academic_year": year}
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(cycle).insert()
		frappe.db.set_value("Accreditation Framework", SCRATCH, "status", "Published")
		self.assertTrue(frappe.get_doc(cycle).insert())

	def test_code_and_version_are_unique_per_framework(self):
		def make(name, code, version):
			return frappe.get_doc(
				{"doctype": "Accreditation Framework", "framework_name": name, "framework_code": code, "version": version}
			)

		make("DP Code A", "DP-CODE", "1").insert()
		with self.assertRaises(frappe.ValidationError):
			make("DP Code B", "DP-CODE", "1").insert()
		self.assertTrue(make("DP Code C", "DP-CODE", "2").insert())

	def test_editable_check_reads_the_status_under_a_row_lock(self):
		make_scratch()
		real = frappe.db.get_value
		calls = []

		def spy(*args, **kwargs):
			calls.append(kwargs.get("for_update"))
			return real(*args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=spy):
			framework.assert_editable(SCRATCH)
		self.assertIn(True, calls)

	def test_publish_takes_the_row_lock_before_it_reads_the_status(self):
		make_scratch()
		doc = frappe.get_doc("Accreditation Framework", SCRATCH)
		doc.status = "Published"
		real = frappe.db.get_value
		calls = []

		def spy(*args, **kwargs):
			calls.append((args[:2], kwargs.get("for_update")))
			return real(*args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=spy):
			doc.save()
		self.assertIn((("Accreditation Framework", SCRATCH), True), calls)
