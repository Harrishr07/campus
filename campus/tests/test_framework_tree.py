"""M01-01 / M01-02 integration test: seeded NAAC AQAR tree, publish lock, clone to a new version."""

import frappe

from campus.iqac import api
from campus.iqac.setup import FRAMEWORK, seed_framework
from campus.tests.utils import CampusTestCase

RESEARCH_NOTE_METRICS = [
	"2.1.1", "2.1.2", "2.2.2", "2.3.3", "2.4.1", "2.4.2", "2.4.3", "2.5.1", "2.5.2", "2.5.3", "2.6.2", "2.6.3",
	"3.2.1", "3.2.2", "3.4.3", "3.4.5", "3.4.6", "3.5.1", "4.1.4", "4.4.1", "5.1.1", "5.1.2", "5.2.1", "5.2.2",
	"5.2.3", "6.3.2", "6.3.3", "6.3.4",
]  # fmt: skip
EXTENDED_PROFILE = ["1.1", "2.1", "2.2", "2.3", "3.1", "3.2", "3.3", "4.1", "4.2", "4.3", "4.4"]
PARENT_TYPE = {"Key Indicator": "Criterion", "Metric": "Key Indicator", "Sub-Metric": "Metric"}
COPIED_FIELDS = [
	"code", "title", "node_type", "answer_type", "choices", "word_limit", "unit", "period", "formula",
	"department_wise", "owner_role", "description",
]  # fmt: skip


def nodes_of(framework):
	return frappe.get_all("Framework Node", {"framework": framework}, ["name", "parent_node", *COPIED_FIELDS], order_by="code")


def make_draft(name):
	doc = frappe.get_doc({"doctype": "Accreditation Framework", "framework_name": name, "version": "1"}).insert()
	for code, node_type, parent in (("1", "Criterion", None), ("1.1", "Key Indicator", "1"), ("1.1.1", "Metric", "1.1")):
		node = {"doctype": "Framework Node", "framework": name, "code": code, "title": f"t{code}", "node_type": node_type}
		if parent:
			node["parent_node"] = f"{name}-{parent}"
		if node_type == "Metric":
			node.update(answer_type="Choice", choices="A\nB", unit="n", evidence_slots=[{"slot_name": "Data Template", "kind": "File"}])
		frappe.get_doc(node).insert()
	return doc


class TestSeededTree(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_framework()

	def codes(self, node_type):
		return {n.code for n in nodes_of(FRAMEWORK) if n.node_type == node_type}

	def test_has_all_seven_criteria_and_the_research_note_metrics(self):
		self.assertEqual(self.codes("Criterion"), {str(i) for i in range(1, 8)})
		self.assertFalse(set(RESEARCH_NOTE_METRICS) - self.codes("Metric"))
		self.assertTrue({"2.5.1.1", "2.6.3.1"} <= self.codes("Sub-Metric"))

	def test_extended_profile_nodes_are_roots(self):
		profile = [n for n in nodes_of(FRAMEWORK) if n.node_type == "Extended Profile"]
		self.assertEqual({n.code for n in profile}, {f"EP-{c}" for c in EXTENDED_PROFILE})
		self.assertFalse([n.name for n in profile if n.parent_node])

	def test_each_node_hangs_under_the_right_kind_of_parent(self):
		by_name = {n.name: n for n in nodes_of(FRAMEWORK)}
		for node in by_name.values():
			if node.node_type in PARENT_TYPE:
				self.assertEqual(by_name[node.parent_node].node_type, PARENT_TYPE[node.node_type], node.code)
				self.assertTrue(node.code.startswith(by_name[node.parent_node].code + "."), node.code)

	def test_seeded_codes_are_unique(self):
		codes = [n.code for n in nodes_of(FRAMEWORK)]
		self.assertEqual(len(codes), len(set(codes)))

	def test_seed_is_published_marked_placeholder_and_idempotent(self):
		before = len(nodes_of(FRAMEWORK))
		seed_framework()
		self.assertEqual(len(nodes_of(FRAMEWORK)), before)
		framework = frappe.get_doc("Accreditation Framework", FRAMEWORK)
		self.assertEqual(framework.status, "Published")
		self.assertIn("placeholder - replace with official template", framework.description)
		unmarked = [n.code for n in nodes_of(FRAMEWORK) if "placeholder - replace with official template" not in (n.description or "")]
		self.assertEqual(unmarked, [])

	def test_seeded_metrics_declare_answer_type_and_evidence_slots(self):
		node = frappe.get_doc("Framework Node", f"{FRAMEWORK}-1.4.1")
		self.assertEqual(node.answer_type, "Choice")
		self.assertTrue(node.choices)
		self.assertEqual(frappe.db.get_value("Framework Node", f"{FRAMEWORK}-2.5.3", "answer_type"), "Narrative")
		self.assertIn("Data Template", [s.slot_name for s in frappe.get_doc("Framework Node", f"{FRAMEWORK}-2.5.1").evidence_slots])


class TestNodeValidation(CampusTestCase):
	def setUp(self):
		super().setUp()
		self.scratch = f"Tree Scratch {self._testMethodName}"  # one framework per test: only the class is rolled back
		make_draft(self.scratch)

	def node(self, **values):
		return frappe.get_doc(
			{"doctype": "Framework Node", "framework": self.scratch, "code": "9", "title": "t", "node_type": "Criterion", **values}
		)

	def test_manual_metric_needs_no_formula_but_a_choice_needs_choices(self):
		self.assertTrue(self.node(code="1.1.2", node_type="Metric", parent_node=f"{self.scratch}-1.1", answer_type="Number").insert())
		with self.assertRaises(frappe.ValidationError):
			self.node(code="1.1.3", node_type="Metric", parent_node=f"{self.scratch}-1.1", answer_type="Choice").insert()

	def test_word_limit_belongs_to_narratives(self):
		with self.assertRaises(frappe.ValidationError):
			self.node(code="1.1.4", node_type="Metric", parent_node=f"{self.scratch}-1.1", answer_type="Number", word_limit=500).insert()
		self.assertTrue(
			self.node(code="1.1.5", node_type="Metric", parent_node=f"{self.scratch}-1.1", answer_type="Narrative", word_limit=500).insert()
		)

	def test_codes_are_unique_per_framework(self):
		with self.assertRaises(frappe.DuplicateEntryError):
			self.node(code="1", title="again").insert()

	def test_parent_must_be_of_the_level_above(self):
		for values in (
			{"node_type": "Key Indicator"},  # no parent
			{"node_type": "Metric", "parent_node": f"{self.scratch}-1"},  # criterion is not a key indicator
			{"node_type": "Criterion", "parent_node": f"{self.scratch}-1"},
			{"node_type": "Extended Profile", "parent_node": f"{self.scratch}-1"},
		):
			with self.subTest(values=values), self.assertRaises(frappe.ValidationError):
				self.node(**values).insert()


class TestPublishLock(CampusTestCase):
	def setUp(self):
		super().setUp()
		self.scratch = f"Tree Scratch {self._testMethodName}"
		self.framework = make_draft(self.scratch)

	def publish(self):
		self.framework.status = "Published"
		self.framework.save()

	def test_blank_code_and_version_are_stored_as_null_so_unversioned_frameworks_coexist(self):
		for name in (f"{self.scratch} A", f"{self.scratch} B"):  # a form sends "" for a blank field
			frappe.get_doc({"doctype": "Accreditation Framework", "framework_name": name, "framework_code": "", "version": ""}).insert()
			self.assertEqual(frappe.db.get_value("Accreditation Framework", name, ["framework_code", "version"]), (None, None))

	def test_draft_is_editable_and_publishing_needs_nodes(self):
		self.framework.description = "edited"
		self.framework.save()
		empty = frappe.get_doc({"doctype": "Accreditation Framework", "framework_name": f"{self.scratch} empty"}).insert()
		empty.status = "Published"
		with self.assertRaises(frappe.ValidationError):
			empty.save()

	def test_published_framework_and_nodes_cannot_be_edited(self):
		self.publish()
		self.framework.reload()
		self.framework.description = "changed"
		with self.assertRaises(frappe.ValidationError):
			self.framework.save()
		node = frappe.get_doc("Framework Node", f"{self.scratch}-1.1.1")
		node.title = "changed"
		with self.assertRaises(frappe.ValidationError):
			node.save()
		with self.assertRaises(frappe.ValidationError):
			node.delete()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Framework Node", "framework": self.scratch, "code": "2", "title": "new", "node_type": "Criterion"}
			).insert()
		with self.assertRaises(frappe.ValidationError):
			self.framework.delete()

	def test_published_can_only_be_retired_and_retired_is_frozen(self):
		self.publish()
		self.framework.reload()
		self.framework.status = "Draft"
		with self.assertRaises(frappe.ValidationError):
			self.framework.save()
		self.framework.reload()
		self.framework.status = "Retired"
		self.framework.save()
		self.framework.status = "Published"
		with self.assertRaises(frappe.ValidationError):
			self.framework.save()

	def test_publishing_with_other_changes_is_refused(self):
		self.publish()
		self.framework.reload()
		self.framework.update({"status": "Retired", "version": "99"})
		with self.assertRaises(frappe.ValidationError):
			self.framework.save()

	def test_valid_to_cannot_precede_valid_from(self):
		self.framework.update({"valid_from": "2025-01-01", "valid_to": "2024-01-01"})
		with self.assertRaises(frappe.ValidationError):
			self.framework.save()


class TestClone(CampusTestCase):
	def setUp(self):
		super().setUp()
		self.scratch = f"Tree Scratch {self._testMethodName}"
		self.source = make_draft(self.scratch)
		self.source.status = "Published"
		self.source.save()

	def test_clone_is_an_editable_draft_with_identical_nodes(self):
		clone = api.clone_framework(self.scratch, f"{self.scratch} v2", "2")
		doc = frappe.get_doc("Accreditation Framework", clone)
		self.assertEqual((doc.status, doc.version, doc.previous_version), ("Draft", "2", self.scratch))
		strip = lambda rows, prefix: [  # noqa: E731
			{**{f: row[f] for f in COPIED_FIELDS}, "parent": row.parent_node and row.parent_node.removeprefix(prefix)} for row in rows
		]
		self.assertEqual(strip(nodes_of(clone), clone + "-"), strip(nodes_of(self.scratch), self.scratch + "-"))
		metric = frappe.get_doc("Framework Node", f"{clone}-1.1.1")
		self.assertEqual([(s.slot_name, s.kind) for s in metric.evidence_slots], [("Data Template", "File")])
		metric.title = "edited in the clone"
		metric.save()
		self.assertEqual(frappe.db.get_value("Framework Node", f"{self.scratch}-1.1.1", "title"), "t1.1.1")

	def test_clone_of_the_seeded_framework_keeps_every_node(self):
		seed_framework()
		clone = api.clone_framework(FRAMEWORK, "Framework Tree Seed Clone", "next")
		self.assertEqual(len(nodes_of(clone)), len(nodes_of(FRAMEWORK)))

	def test_clone_needs_a_new_unused_name_and_the_create_right(self):
		with self.assertRaises(frappe.ValidationError):
			api.clone_framework(self.scratch, self.scratch, "2")
		user = "framework-tree-plain@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "Plain", "send_welcome_email": 0}).insert()
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			api.clone_framework(self.scratch, f"{self.scratch} denied", "2")
