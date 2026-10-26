"""M01-02 / M01-03 (P3-T03) Accreditation Cycle: status flow, owners per criterion with tasks, approval, lock."""

import frappe

from campus.campus_platform.approvals import approve, reject, request_approval
from campus.iqac import api, compute
from campus.iqac import cycle as lifecycle
from campus.iqac.setup import FRAMEWORK
from campus.tests.approval_fixtures import level
from campus.tests.factories import make_user
from campus.tests.test_iqac import COORDINATOR, FACULTY_USER, IqacFixture
from campus.tests.test_results import COLLEGE

APPROVER = "iqac-principal@example.com"
OWNER_A, OWNER_B = "iqac-owner-a@example.com", "iqac-owner-b@example.com"
POLICY = "IQAC Cycle Test Policy"
CRITERION_2, CRITERION_3 = f"{FRAMEWORK}-2", f"{FRAMEWORK}-3"


class CycleFixture(IqacFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for user in (APPROVER, OWNER_A, OWNER_B):
			make_user(user, [COLLEGE])
		frappe.get_doc("User", APPROVER).add_roles("Principal")

	def setUp(self):
		super().setUp()
		frappe.db.delete(
			"Approval Level", {"parenttype": "Approval Policy", "parent": ["in", self.policies()]}
		)
		frappe.db.delete("Approval Policy", {"document_type": "Accreditation Cycle"})

	def policies(self):
		return frappe.get_all("Approval Policy", {"document_type": "Accreditation Cycle"}, pluck="name") or [
			""
		]

	def make_policy(self, **extra):
		return frappe.get_doc(
			{
				"doctype": "Approval Policy", "policy_name": POLICY, "document_type": "Accreditation Cycle",
				"levels": [level("User", APPROVER, title="Principal")], **extra,
			}
		).insert()  # fmt: skip

	def to_review(self):
		lifecycle.advance(self.cycle.name)
		lifecycle.advance(self.cycle.name)

	def status(self):
		return frappe.db.get_value("Accreditation Cycle", self.cycle.name, "status")


class TestStatusFlow(CycleFixture):
	def test_a_new_cycle_is_collecting_and_status_cannot_be_edited_by_hand(self):
		self.assertEqual(self.status(), "Collecting")
		doc = frappe.get_doc("Accreditation Cycle", self.cycle.name)
		doc.status = "Approved"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual(self.status(), "Collecting")

	def test_advance_walks_collecting_validating_review_and_stops_before_approval(self):
		lifecycle.advance(self.cycle.name)
		self.assertEqual(self.status(), "Validating")
		lifecycle.advance(self.cycle.name)
		self.assertEqual(self.status(), "IQAC Review")
		with self.assertRaisesRegex(frappe.ValidationError, "approval"):
			lifecycle.advance(self.cycle.name)  # Approved only through the approval engine
		self.assertEqual(self.status(), "IQAC Review")

	def test_reopen_goes_back_to_collecting_before_approval_only(self):
		self.to_review()
		lifecycle.reopen(self.cycle.name)
		self.assertEqual(self.status(), "Collecting")
		with self.assertRaises(frappe.ValidationError):
			lifecycle.reopen(self.cycle.name)  # already Collecting

	def test_advance_and_reopen_need_the_iqac_role_and_the_cycles_company(self):
		frappe.set_user(FACULTY_USER)
		with self.assertRaises(frappe.PermissionError):
			api.advance_cycle(self.cycle.name)
		frappe.set_user(COORDINATOR)
		api.advance_cycle(self.cycle.name)
		self.assertEqual(self.status(), "Validating")
		api.reopen_cycle(self.cycle.name)
		self.assertEqual(self.status(), "Collecting")


class TestOwnersAndTasks(CycleFixture):
	def set_owners(self, *rows):
		doc = frappe.get_doc("Accreditation Cycle", self.cycle.name)
		for criterion, owner in rows:
			doc.append("owners", {"criterion": criterion, "user": owner})
		doc.save()
		return doc

	def todos(self, user):
		return frappe.get_all(
			"ToDo",
			{
				"reference_type": "Accreditation Cycle",
				"reference_name": self.cycle.name,
				"allocated_to": user,
				"status": "Open",
			},
			pluck="description",
		)

	def test_each_criterion_owner_gets_one_task_and_the_owner_role(self):
		self.set_owners((CRITERION_2, OWNER_A), (CRITERION_3, OWNER_B))
		self.assertEqual(len(self.todos(OWNER_A)), 1)
		self.assertIn("2", self.todos(OWNER_A)[0])
		self.assertEqual(len(self.todos(OWNER_B)), 1)
		self.assertTrue(frappe.db.exists("Has Role", {"parent": OWNER_A, "role": "IQAC Criterion Owner"}))

	def test_saving_again_does_not_duplicate_tasks_and_a_new_owner_gets_one(self):
		doc = self.set_owners((CRITERION_2, OWNER_A))
		doc.reload()
		doc.save()
		doc.append("owners", {"criterion": CRITERION_3, "user": OWNER_A})
		doc.save()
		self.assertEqual(len(self.todos(OWNER_A)), 2)

	def test_owner_must_sit_on_a_criterion_of_the_cycles_framework_once(self):
		for rows in (
			[(f"{FRAMEWORK}-2.1", OWNER_A)],  # a key indicator
			[(CRITERION_2, OWNER_A), (CRITERION_2, OWNER_A)],
		):
			with self.subTest(rows=rows), self.assertRaises(frappe.ValidationError):
				self.set_owners(*rows)

	def test_tasks_are_not_made_for_a_locked_cycle(self):
		self.make_policy()
		self.to_review()
		request = request_approval("Accreditation Cycle", self.cycle.name)
		frappe.set_user(APPROVER)
		approve(request)
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			self.set_owners((CRITERION_2, OWNER_A))
		self.assertEqual(self.todos(OWNER_A), [])


class TestApprovalAndLock(CycleFixture):
	def approve_cycle(self):
		request = request_approval("Accreditation Cycle", self.cycle.name)
		frappe.set_user(APPROVER)
		approve(request)
		frappe.set_user("Administrator")
		return request

	def test_approval_is_requested_only_in_iqac_review_and_needs_a_matching_policy(self):
		self.make_policy()
		with self.assertRaisesRegex(frappe.ValidationError, "IQAC Review"):
			request_approval("Accreditation Cycle", self.cycle.name)
		self.to_review()
		frappe.db.delete(
			"Approval Level", {"parenttype": "Approval Policy", "parent": ["in", self.policies()]}
		)
		frappe.db.delete("Approval Policy", {"document_type": "Accreditation Cycle"})
		with self.assertRaisesRegex(frappe.ValidationError, "Approval Policy"):
			request_approval(
				"Accreditation Cycle", self.cycle.name
			)  # never approved by the engine's no-policy shortcut
		self.assertEqual(self.status(), "IQAC Review")

	def test_a_policy_whose_final_action_is_not_submit_is_refused(self):
		self.make_policy(on_final_action="Set Field", final_field="status", final_value="Approved")
		self.to_review()
		with self.assertRaisesRegex(frappe.ValidationError, "Submit"):
			request_approval("Accreditation Cycle", self.cycle.name)

	def test_final_approval_sets_approved_and_locks_every_value(self):
		self.make_policy()
		self.make_results()
		compute.compute_cycle(self.cycle.name)
		lifecycle.prepare_values(self.cycle.name)
		self.to_review()
		self.approve_cycle()
		self.assertEqual(
			(self.status(), frappe.db.get_value("Accreditation Cycle", self.cycle.name, "docstatus")),
			("Approved", 1),
		)
		statuses = frappe.get_all("Metric Value", {"cycle": self.cycle.name}, pluck="status")
		self.assertGreater(len(statuses), 2)
		self.assertEqual(set(statuses), {"Locked"})

	def test_pending_or_rejected_approval_does_not_approve_or_lock(self):
		self.make_policy()
		self.make_results()
		compute.compute_cycle(self.cycle.name)
		self.to_review()
		request = request_approval("Accreditation Cycle", self.cycle.name)
		self.assertEqual(self.status(), "IQAC Review")
		frappe.set_user(APPROVER)
		reject(request, "Not yet")
		frappe.set_user("Administrator")
		self.assertEqual(self.status(), "IQAC Review")
		self.assertNotIn("Locked", frappe.get_all("Metric Value", {"cycle": self.cycle.name}, pluck="status"))

	def test_nothing_changes_after_approval_and_it_can_be_submitted(self):
		self.make_policy()
		self.make_results()
		compute.compute_cycle(self.cycle.name)
		self.to_review()
		self.approve_cycle()
		with self.assertRaises(frappe.ValidationError):
			compute.compute_cycle(self.cycle.name)  # values are locked
		with self.assertRaises(frappe.ValidationError):
			lifecycle.reopen(self.cycle.name)
		doc = frappe.get_doc("Accreditation Cycle", self.cycle.name)
		doc.append("owners", {"criterion": CRITERION_2, "user": OWNER_A})
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		lifecycle.advance(self.cycle.name)
		self.assertEqual(self.status(), "Submitted")
		self.assertEqual(
			set(frappe.get_all("Metric Value", {"cycle": self.cycle.name}, pluck="status")), {"Locked"}
		)
