"""M17-03 integration tests: level-by-level flow, policy conditions, reject/return, immutable trail,
permission checks and the edit lock, on the test-only Approval Test Document."""

from unittest.mock import patch

import frappe

from campus.campus_platform.approvals import (
	approval_summary,
	approve,
	reject,
	request_approval,
	return_for_changes,
)
from campus.tests import approval_fixtures as fx
from campus.tests.utils import CampusTestCase


class ApprovalTestCase(CampusTestCase):
	@classmethod
	def load_demo_data(cls):
		cls.department = fx.setup_world()

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		fx.clear_approval_data()
		fx.make_standard_policies()

	def new_request(self, amount=60000, **extra):
		doc = fx.make_document(amount, self.department, **extra)
		return doc, request_approval(fx.DOCTYPE, doc.name)

	def act_as(self, user, method, request, comment=None):
		frappe.set_user(user)
		try:
			return method(request, comment)
		finally:
			frappe.set_user("Administrator")

	def request(self, name):
		return frappe.get_doc("Approval Request", name)


class TestApprovalFlow(ApprovalTestCase):
	def test_three_levels_move_one_by_one_and_submit_after_final_approval(self):
		doc, name = self.new_request()
		request = self.request(name)
		self.assertEqual((request.status, request.current_level, request.policy), ("Pending", 1, fx.BIG))
		self.assertEqual([a.user for a in request.approvers], [fx.HOD])
		self.assertTrue(fx.notified(fx.HOD))

		for user, next_level in ((fx.HOD, 2), (fx.DEAN, 3)):
			self.assertEqual(self.act_as(user, approve, name), "Pending")
			self.assertEqual(self.request(name).current_level, next_level)
			doc.reload()
			self.assertEqual(doc.docstatus, 0)
		self.assertTrue(fx.notified(fx.PRINCIPAL))

		self.assertEqual(self.act_as(fx.PRINCIPAL, approve, name, "Fine"), "Approved")
		doc.reload()
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(
			fx.actions_of(self.request(name)),
			[("Request", 0, "Administrator", None), ("Approve", 1, fx.HOD, None),
			 ("Approve", 2, fx.DEAN, None), ("Approve", 3, fx.PRINCIPAL, None)],
		)  # fmt: skip

	def test_direct_submit_is_blocked_while_a_policy_matches(self):
		doc = fx.make_document(60000, self.department)
		with self.assertRaisesRegex(frappe.ValidationError, "needs approval"):
			doc.submit()

	def test_direct_submit_is_blocked_while_pending(self):
		doc, _name = self.new_request()
		doc.reload()
		with self.assertRaisesRegex(frappe.ValidationError, "awaiting approval"):
			doc.submit()

	def test_second_request_while_pending_is_refused(self):
		doc, _name = self.new_request()
		with self.assertRaises(frappe.ValidationError):
			request_approval(fx.DOCTYPE, doc.name)

	def test_level_without_any_approver_is_refused(self):
		doc = fx.make_document(60000, fx.make_department("Approval Test Empty", fx.COLLEGE))
		with self.assertRaisesRegex(frappe.ValidationError, "approver"):
			request_approval(fx.DOCTYPE, doc.name)

	def test_min_approvals_waits_for_enough_distinct_approvers(self):
		frappe.get_doc("User", fx.DEAN).add_roles("Accounts User")
		frappe.get_doc("User", fx.PRINCIPAL).add_roles("Accounts User")
		fx.make_policy(
			"APR Test Two Of Role", [fx.level("Role", "Accounts User", min_approvals=2)], priority=99
		)
		_doc, name = self.new_request()
		self.assertEqual(self.act_as(fx.DEAN, approve, name), "Pending")
		self.assertEqual(self.act_as(fx.PRINCIPAL, approve, name), "Approved")

	def test_an_approver_who_cannot_open_the_document_is_dropped_when_others_remain(self):
		frappe.get_doc("User", fx.DEAN).add_roles("Accounts User")
		frappe.get_doc("User", fx.OTHER_DELEGATE).add_roles("Accounts User")  # restricted to another company
		fx.make_policy(
			"APR Test Mixed Readers", [fx.level("Role", "Accounts User", limit_to_company=0)], priority=99
		)
		_doc, name = self.new_request()
		approvers = frappe.get_all("Approval Request Approver", {"parent": name}, pluck="user")
		self.assertIn(fx.DEAN, approvers)
		self.assertNotIn(fx.OTHER_DELEGATE, approvers)

	def test_too_few_readable_approvers_are_refused_naming_the_blind_ones(self):
		frappe.get_doc("User", fx.DEAN).add_roles("Accounts User")
		frappe.get_doc("User", fx.OTHER_DELEGATE).add_roles("Accounts User")
		fx.make_policy(
			"APR Test Too Few",
			[fx.level("Role", "Accounts User", min_approvals=50, limit_to_company=0)],
			priority=99,
		)
		doc = fx.make_document(60000, self.department)
		with self.assertRaisesRegex(frappe.ValidationError, "Approvers .*cannot open"):
			request_approval(fx.DOCTYPE, doc.name)

	def test_set_field_final_action_keeps_draft_and_freezes_it(self):
		fx.make_policy(
			"APR Test Set Field", [fx.level("User", fx.CLERK)], priority=99,
			on_final_action="Set Field", final_field="notes", final_value="approved",
		)  # fmt: skip
		doc, name = self.new_request()
		self.act_as(fx.CLERK, approve, name)
		doc.reload()
		self.assertEqual((doc.docstatus, doc.notes), (0, "approved"))
		doc.amount = 70000
		with self.assertRaisesRegex(frappe.ValidationError, "approved"):
			doc.save()
		doc.reload()
		doc.submit()
		self.assertEqual(doc.docstatus, 1)


class TestPolicyCondition(ApprovalTestCase):
	def test_condition_selects_between_two_policies(self):
		_doc, big = self.new_request(60000)
		_doc, small = self.new_request(5000)
		self.assertEqual(self.request(big).policy, fx.BIG)
		self.assertEqual(self.request(small).policy, fx.SMALL)
		self.assertEqual([a.user for a in self.request(small).approvers], [fx.CLERK])

	def test_no_matching_policy_submits_directly(self):
		doc, name = self.new_request(500)
		self.assertIsNone(name)
		doc.reload()
		self.assertEqual(doc.docstatus, 1)
		self.assertFalse(frappe.db.exists("Approval Request", {"reference_name": doc.name}))

	def test_plain_submit_works_without_matching_policy(self):
		doc = fx.make_document(500, self.department)
		doc.submit()
		self.assertEqual(doc.docstatus, 1)

	def test_policy_of_other_company_does_not_apply(self):
		fx.make_policy(
			"APR Test Other", [fx.level("User", fx.OUTSIDER)], priority=99, company=fx.OTHER_COLLEGE
		)
		_doc, name = self.new_request(5000)
		self.assertEqual(self.request(name).policy, fx.SMALL)


class TestRejectAndReturn(ApprovalTestCase):
	def test_reject_needs_a_comment(self):
		_doc, name = self.new_request()
		with self.assertRaisesRegex(frappe.ValidationError, "comment"):
			self.act_as(fx.HOD, reject, name, "  ")
		self.assertEqual(self.request(name).status, "Pending")

	def test_rejection_keeps_draft_records_comment_and_allows_a_new_request(self):
		doc, name = self.new_request()
		self.act_as(fx.HOD, approve, name)
		self.assertEqual(self.act_as(fx.DEAN, reject, name, "Over budget"), "Rejected")
		doc.reload()
		self.assertEqual(doc.docstatus, 0)
		last = self.request(name).actions[-1]
		self.assertEqual((last.action, last.approver, last.comment), ("Reject", fx.DEAN, "Over budget"))
		with self.assertRaises(frappe.ValidationError):
			self.act_as(fx.PRINCIPAL, approve, name)
		self.assertNotEqual(request_approval(fx.DOCTYPE, doc.name), name)

	def test_return_needs_a_comment(self):
		_doc, name = self.new_request()
		with self.assertRaisesRegex(frappe.ValidationError, "comment"):
			self.act_as(fx.HOD, return_for_changes, name)

	def test_return_unlocks_the_draft_and_resubmission_starts_a_new_cycle(self):
		doc, name = self.new_request()
		self.assertEqual(self.act_as(fx.HOD, return_for_changes, name, "Split it"), "Returned")
		doc.reload()
		doc.amount = 5000
		doc.save()
		self.assertEqual(request_approval(fx.DOCTYPE, doc.name), name)
		request = self.request(name)
		self.assertEqual((request.cycle, request.current_level, request.policy), (2, 1, fx.SMALL))
		self.assertEqual([(a.cycle, a.user) for a in request.approvers], [(1, fx.HOD), (2, fx.CLERK)])


class TestImmutableTrail(ApprovalTestCase):
	def test_action_rows_cannot_be_edited(self):
		_doc, name = self.new_request()
		self.act_as(fx.HOD, approve, name, "ok")
		request = self.request(name)
		request.actions[-1].comment = "changed"
		with self.assertRaisesRegex(frappe.ValidationError, "permanent"):
			request.save(ignore_permissions=True)

	def test_action_rows_cannot_be_removed(self):
		_doc, name = self.new_request()
		request = self.request(name)
		request.actions = []
		with self.assertRaisesRegex(frappe.ValidationError, "removed"):
			request.save(ignore_permissions=True)

	def test_request_cannot_be_deleted(self):
		_doc, name = self.new_request()
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be deleted"):
			frappe.delete_doc("Approval Request", name)

	def test_deleting_the_document_removes_its_requests(self):
		doc, name = self.new_request()
		self.act_as(fx.HOD, return_for_changes, name, "no")
		frappe.delete_doc(fx.DOCTYPE, doc.name)
		self.assertFalse(frappe.db.exists("Approval Request", name))


class TestPermissions(ApprovalTestCase):
	def test_non_approver_gets_permission_error(self):
		_doc, name = self.new_request()
		for method in (approve, reject, return_for_changes):
			with self.assertRaises(frappe.PermissionError):
				self.act_as(fx.OUTSIDER, method, name, "x")

	def test_approver_of_a_later_level_cannot_act_early(self):
		_doc, name = self.new_request()
		with self.assertRaises(frappe.PermissionError):
			self.act_as(fx.PRINCIPAL, approve, name)

	def test_approver_cannot_approve_twice(self):
		for user in (fx.HOD, fx.DEAN):
			frappe.get_doc("User", user).add_roles("Accounts User")
		fx.make_policy(
			"APR Test Two Of Role", [fx.level("Role", "Accounts User", min_approvals=2)], priority=99
		)
		_doc, name = self.new_request()
		self.act_as(fx.HOD, approve, name)
		with self.assertRaisesRegex(frappe.ValidationError, "already approved"):
			self.act_as(fx.HOD, approve, name)
		self.assertEqual(self.request(name).status, "Pending")

	def test_request_visibility(self):
		_doc, name = self.new_request()
		request = self.request(name)
		self.assertTrue(frappe.has_permission("Approval Request", doc=request, user=fx.HOD))
		self.assertFalse(frappe.has_permission("Approval Request", doc=request, user=fx.OUTSIDER))
		frappe.set_user(fx.OUTSIDER)
		self.assertNotIn(name, frappe.get_list("Approval Request", pluck="name"))
		frappe.set_user(fx.HOD)
		self.assertIn(name, frappe.get_list("Approval Request", pluck="name"))


class TestEditLock(ApprovalTestCase):
	def test_owner_cannot_change_a_pending_document(self):
		doc, _name = self.new_request()
		doc.reload()
		doc.amount = 99999
		with self.assertRaisesRegex(frappe.ValidationError, "amount"):
			doc.save()

	def test_current_approver_may_change_the_level_editable_fields_only(self):
		doc, _name = self.new_request()
		frappe.set_user(fx.HOD)
		doc.reload()
		doc.notes = "checked by HOD"
		doc.save(ignore_permissions=True)
		doc.amount = 1
		with self.assertRaisesRegex(frappe.ValidationError, "amount"):
			doc.save(ignore_permissions=True)

	def test_summary_reports_status_trail_and_what_the_user_can_do(self):
		doc, name = self.new_request()
		summary = approval_summary(doc)
		self.assertEqual(
			(summary["request"], summary["status"], summary["can_act"]), (name, "Pending", False)
		)
		frappe.set_user(fx.HOD)
		self.assertTrue(approval_summary(doc)["can_act"])


class TestSeparationOfDuties(ApprovalTestCase):
	def test_requester_is_never_resolved_as_approver(self):
		fx.make_policy("APR Test Self", [fx.level("User", "Administrator")], priority=99)
		doc = fx.make_document(60000, self.department)
		with self.assertRaisesRegex(frappe.ValidationError, "requester"):
			request_approval(fx.DOCTYPE, doc.name)

	def test_document_owner_is_never_resolved_as_approver(self):
		fx.make_policy("APR Test Owner", [fx.level("Field", "approver_user")], priority=99)
		frappe.set_user(fx.CLERK)
		doc = frappe.get_doc(
			{
				"doctype": fx.DOCTYPE,
				"title": "own",
				"amount": 10,
				"company": fx.COLLEGE,
				"approver_user": fx.CLERK,
			}
		).insert(ignore_permissions=True)
		frappe.set_user("Administrator")
		with self.assertRaisesRegex(frappe.ValidationError, "requester"):
			request_approval(fx.DOCTYPE, doc.name)

	def test_requester_cannot_approve_as_a_delegate(self):
		frappe.get_doc(
			{"doctype": "Approval Delegation", "user": fx.HOD, "delegate": "Administrator",
			 "from_date": frappe.utils.today(), "to_date": frappe.utils.today()}
		).insert()  # fmt: skip
		_doc, name = self.new_request()
		with self.assertRaisesRegex(frappe.PermissionError, "own"):
			approve(name)
		self.assertEqual(self.request(name).current_level, 1)


def registered_hooks(*methods):
	"""Patch frappe.get_hooks so `approval_final_actions` lists `methods`."""
	original = frappe.get_hooks

	def get_hooks(hook=None, *args, **kwargs):
		if hook == "approval_final_actions":
			return list(methods)
		return original(hook, *args, **kwargs)

	return patch("frappe.get_hooks", side_effect=get_hooks)


class TestCallServiceFinalAction(ApprovalTestCase):
	SERVICE = "campus.tests.approval_fixtures.mark_serviced"

	def make_service_policy(self):
		fx.make_policy(
			"APR Test Service", [fx.level("User", fx.CLERK)], priority=99,
			on_final_action="Call Service", final_method=self.SERVICE,
		)  # fmt: skip

	def test_registered_method_runs_on_final_approval(self):
		with registered_hooks(self.SERVICE):
			self.make_service_policy()
			doc, name = self.new_request()
			self.act_as(fx.CLERK, approve, name)
		doc.reload()
		self.assertEqual((doc.docstatus, doc.notes), (0, f"serviced by {name}"))

	def test_method_is_rechecked_when_it_runs(self):
		with registered_hooks(self.SERVICE):
			self.make_service_policy()
		_doc, name = self.new_request()
		with self.assertRaisesRegex(frappe.ValidationError, "approval_final_actions"):
			self.act_as(fx.CLERK, approve, name)


class TestBeforeApprovalRequestHook(ApprovalTestCase):
	def test_a_document_can_refuse_the_request_before_one_is_created(self):
		doc = fx.make_document(60000, self.department, notes="refuse-request")
		with self.assertRaises(frappe.ValidationError):
			request_approval(fx.DOCTYPE, doc.name)
		self.assertFalse(
			frappe.db.exists(
				"Approval Request", {"reference_doctype": fx.DOCTYPE, "reference_name": doc.name}
			)
		)
		doc.db_set("notes", "fine")
		self.assertTrue(request_approval(fx.DOCTYPE, doc.name))
