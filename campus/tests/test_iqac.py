"""M15-01 integration test: live AQAR metrics (2.1.1, 2.6.3) with drill-down, formula sandbox, permissions."""

import json

import frappe

from campus.iqac import api, compute
from campus.iqac.formula import evaluate
from campus.iqac.report.metric_drill_down import metric_drill_down
from campus.iqac.setup import FRAMEWORK, seed_framework
from campus.tests.factories import make_company, make_user
from campus.tests.test_regulation import year_name
from campus.tests.test_results import COLLEGE, ExamFixture

OTHER_COLLEGE = "Iqac Other College"
COORDINATOR, OTHER_COORDINATOR, FACULTY_USER = (
	"iqac-coord@example.com", "iqac-other@example.com", "iqac-plain@example.com",
)  # fmt: skip
NODE_26_3, NODE_21_1 = f"{FRAMEWORK}-2.6.3", f"{FRAMEWORK}-2.1.1"


class IqacFixture(ExamFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_framework()
		make_company(OTHER_COLLEGE, "IQOC")
		make_user(COORDINATOR, [COLLEGE])
		make_user(OTHER_COORDINATOR, [OTHER_COLLEGE])
		make_user(FACULTY_USER, [COLLEGE])
		for user in (COORDINATOR, OTHER_COORDINATOR):
			frappe.get_doc("User", user).add_roles("IQAC Coordinator")

	def setUp(self):
		super().setUp()
		self.cycle = self.make_cycle(COLLEGE)

	def make_cycle(self, company):
		return frappe.get_doc(
			{
				"doctype": "Accreditation Cycle", "framework": FRAMEWORK, "company": company,
				"academic_year": year_name("2022"),
			}
		).insert()  # fmt: skip

	def make_results(self):
		"""Final-year session results: s22 and s26 pass everything, s_ab fails/absent, s_sa is all SA.

		The pre-session (same academic year, not final year) holds a further Student Result that must not count."""
		for student in (self.s22, self.s26):  # lift the ESE-44% fail so both pass every course
			offering = (self.offerings22 if student is self.s22 else self.offerings26)["EXM FA"]
			sheet = frappe.db.get_value(
				"Mark Sheet Entry", {"exam_session": self.session.name, "course_offering": offering}
			)
			frappe.db.set_value("Mark Sheet Entry Row", {"parent": sheet, "student": student.name}, "ese", 40)
		self.run_session()
		frappe.db.set_value("Exam Session", self.session.name, {"is_final_year": 1, "status": "Published"})


class TestLiveMetrics(IqacFixture):
	def metric(self, node):
		return frappe.get_doc("Metric Value", f"{self.cycle.name}-{node.rsplit('-', 1)[1]}")

	def test_pass_percentage_equals_the_hand_count_and_drilldown_lists_those_results(self):
		self.make_results()
		compute.compute_cycle(self.cycle.name)
		metric = self.metric(NODE_26_3)
		# hand count: appeared = s22, s26, s_ab (s_sa is all SA, the pre-session is not final year); passed = s22, s26
		self.assertEqual(metric.value, 66.67)
		snapshot = json.loads(metric.snapshot)
		sr = lambda student: f"SR-{self.session.name}-{student.name}"  # noqa: E731
		self.assertEqual(
			[r["name"] for r in snapshot["inputs"]["final_year_passed"]["records"]],
			sorted([sr(self.s22), sr(self.s26)]),
		)
		self.assertEqual(snapshot["inputs"]["final_year_appeared"]["value"], 3)
		self.assertIn("final_year_passed", snapshot["formula"])
		rows = metric_drill_down.data(frappe._dict(metric_value=metric.name))
		passed = [r for r in rows if r["input"] == "final_year_passed"]
		self.assertEqual({(r["document_type"], r["record"]) for r in passed},
			{("Student Result", sr(self.s22)), ("Student Result", sr(self.s26))})  # fmt: skip
		self.assertEqual(len([r for r in rows if r["input"] == "final_year_appeared"]), 3)

	def test_students_admitted_counts_submitted_enrollments_of_the_company_and_year(self):
		compute.compute_cycle(self.cycle.name)
		metric = self.metric(NODE_21_1)
		enrollments = frappe.get_all(
			"Program Enrollment",
			{"oc_company": COLLEGE, "academic_year": year_name("2022"), "docstatus": 1},
			pluck="name",
		)
		self.assertEqual(metric.value, 4)
		self.assertEqual(sorted(r["name"] for r in json.loads(metric.snapshot)["inputs"]["students_admitted"]["records"]),
			sorted(enrollments))  # fmt: skip

	def test_unpublished_final_year_session_is_not_counted(self):
		self.make_results()
		frappe.db.set_value("Exam Session", self.session.name, "status", "Marks Entry")
		compute.compute_cycle(self.cycle.name)
		self.assertEqual(self.metric(NODE_26_3).value, 0)

	def test_recompute_updates_in_place_and_zero_appeared_gives_zero(self):
		compute.compute_cycle(self.cycle.name)
		self.assertEqual(self.metric(NODE_26_3).value, 0)
		self.make_results()
		compute.compute_cycle(self.cycle.name)
		self.assertEqual(self.metric(NODE_26_3).value, 66.67)
		self.assertEqual(frappe.db.count("Metric Value", {"cycle": self.cycle.name}), 2)

	def test_cycle_is_unique_per_framework_company_and_year(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_cycle(COLLEGE)


class TestFormulaSandbox(IqacFixture):
	def test_formula_cannot_reach_anything_outside_the_data_point_namespace(self):
		for formula in (
			"frappe.db.get_value('User', 'Administrator', 'name')",
			"__import__('os').getcwd()",
			"students_admitted.__class__",
			"().__class__.__bases__",
			"open('/etc/passwd')",
			"getattr(students_admitted, 'real')",
			"final_year_passed",  # a data point that was not provided
		):
			with self.subTest(formula=formula), self.assertRaises(Exception):
				evaluate(formula, {"students_admitted": 1})

	def test_namespace_has_the_data_points_and_round_min_max(self):
		self.assertEqual(evaluate("round(max(a, b) / min(a, b), 1)", {"a": 3, "b": 2}), 1.5)

	def test_node_rejects_unknown_keys_bad_syntax_and_formula_on_non_metrics(self):
		scratch = "Iqac Scratch Framework"  # the seeded framework is published, so its nodes are locked
		if not frappe.db.exists("Accreditation Framework", scratch):
			frappe.get_doc({"doctype": "Accreditation Framework", "framework_name": scratch}).insert()
			for code, node_type, parent in (("9", "Criterion", None), ("9.9", "Key Indicator", "9")):
				frappe.get_doc(
					{"doctype": "Framework Node", "framework": scratch, "code": code, "title": "t", "node_type": node_type,
						"parent_node": parent and f"{scratch}-{parent}"}
				).insert()  # fmt: skip

		def node(**values):
			return frappe.get_doc(
				{"doctype": "Framework Node", "framework": scratch, "code": "9.9.9", "title": "t", "node_type": "Metric",
					"parent_node": f"{scratch}-9.9", **values}
			)  # fmt: skip

		for values in (
			{"formula": "students_admitted + unknown_key"},
			{"formula": "students_admitted +"},
			{"formula": "frappe.session.user"},
			{"formula": "(lambda: 1)()"},
			{"node_type": "Criterion", "parent_node": None, "formula": "students_admitted"},
		):
			with self.subTest(values=values), self.assertRaises(frappe.ValidationError):
				node(**values).insert()
		self.assertTrue(node(formula="students_admitted * 2").insert())


class TestComputeAccess(IqacFixture):
	def test_compute_needs_the_iqac_role_and_the_cycles_company(self):
		frappe.set_user(FACULTY_USER)
		with self.assertRaises(frappe.PermissionError):
			api.compute_cycle(self.cycle.name)
		frappe.set_user(OTHER_COORDINATOR)
		with self.assertRaises(frappe.PermissionError):
			api.compute_cycle(self.cycle.name)
		frappe.set_user(COORDINATOR)
		self.assertEqual(len(api.compute_cycle(self.cycle.name)), 2)

	def test_drilldown_is_company_scoped(self):
		compute.compute_cycle(self.cycle.name)
		name = f"{self.cycle.name}-2.1.1"
		frappe.set_user(COORDINATOR)
		self.assertTrue(metric_drill_down.data(frappe._dict(metric_value=name)))
		frappe.set_user(OTHER_COORDINATOR)
		with self.assertRaises(frappe.PermissionError):
			metric_drill_down.data(frappe._dict(metric_value=name))
		frappe.set_user(FACULTY_USER)
		with self.assertRaises(frappe.PermissionError):
			metric_drill_down.data(frappe._dict(metric_value=name))
