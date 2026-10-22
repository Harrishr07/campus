"""M17-03 integration tests: SLA due time, the hourly escalation job, delegation window and the
My Pending Approvals report."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, now_datetime, today

from campus.campus_platform.approval_escalation import escalate_overdue
from campus.campus_platform.approvals import approve
from campus.campus_platform.report.my_pending_approvals.my_pending_approvals import execute
from campus.tests import approval_fixtures as fx
from campus.tests.test_approvals import ApprovalTestCase


def make_delegation(user, delegate, from_date, to_date, document_types=()):
	return frappe.get_doc(
		{
			"doctype": "Approval Delegation",
			"user": user,
			"delegate": delegate,
			"from_date": from_date,
			"to_date": to_date,
			"document_types": [{"document_type": dt} for dt in document_types],
		}
	).insert()


class TestSlaEscalation(ApprovalTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")  # the job commits per request; keep tests rolled back
		commit.start()
		self.addCleanup(commit.stop)

	def make_overdue(self, name):
		frappe.db.set_value("Approval Request", name, "due_at", add_to_date(now_datetime(), hours=-1))

	def test_due_at_is_level_start_plus_sla_hours(self):
		_doc, name = self.new_request()
		request = self.request(name)
		self.assertEqual(get_datetime(request.due_at), add_to_date(request.level_started_at, hours=24))

	def test_level_without_sla_has_no_due_time(self):
		_doc, name = self.new_request()
		self.act_as(fx.HOD, approve, name)
		self.assertIsNone(self.request(name).due_at)

	def test_overdue_level_escalates_once_and_notifies(self):
		_doc, name = self.new_request()
		self.make_overdue(name)
		escalate_overdue()
		escalate_overdue()
		request = self.request(name)
		self.assertTrue(request.escalated)
		self.assertEqual(
			[(a.user, a.source) for a in request.approvers],
			[(fx.HOD, "Approver"), (fx.ESCALATOR, "Escalation")],
		)
		self.assertEqual([a.action for a in request.actions].count("Escalate"), 1)
		self.assertEqual(len(fx.notified(fx.ESCALATOR)), 1)

	def test_original_approver_can_still_act_after_escalation(self):
		_doc, name = self.new_request()
		self.make_overdue(name)
		escalate_overdue()
		self.assertEqual(self.act_as(fx.HOD, approve, name), "Pending")
		self.assertEqual(self.request(name).current_level, 2)

	def test_escalation_approver_can_act(self):
		_doc, name = self.new_request()
		self.make_overdue(name)
		escalate_overdue()
		self.act_as(fx.ESCALATOR, approve, name)
		self.assertEqual(self.request(name).current_level, 2)

	def test_failed_escalation_is_recorded_once_and_not_retried(self):
		fx.make_policy(
			"APR Test Broken Escalation",
			[fx.level("User", fx.HOD, sla_hours=1, escalate_to_type="Position", escalate_to="DEAN-ACADEMICS",
				escalate_scope_field="approver_user")],
			priority=99,
		)  # fmt: skip
		_doc, name = self.new_request()  # approver_user is empty, so the escalation scope can't resolve
		self.make_overdue(name)
		title = f"Approval escalation failed for {name}"
		escalate_overdue()
		escalate_overdue()
		request = self.request(name)
		self.assertTrue(request.escalated)
		escalations = [a for a in request.actions if a.action == "Escalate"]
		self.assertEqual(len(escalations), 1)
		self.assertIn("Escalation failed", escalations[0].comment)
		self.assertEqual(frappe.db.count("Error Log", {"method": title}), 1)
		self.assertEqual(self.act_as(fx.HOD, approve, name), "Approved")

	def test_level_not_yet_due_is_left_alone(self):
		_doc, name = self.new_request()
		escalate_overdue()
		self.assertFalse(self.request(name).escalated)
		self.assertFalse(fx.notified(fx.ESCALATOR))

	def test_next_level_resets_escalation(self):
		fx.make_policy(
			"APR Test Escalating",
			[fx.level("User", fx.HOD, sla_hours=1), fx.level("User", fx.DEAN, sla_hours=2)],
			priority=99,
		)
		_doc, name = self.new_request()
		self.make_overdue(name)
		escalate_overdue()
		self.act_as(fx.HOD, approve, name)
		request = self.request(name)
		self.assertEqual((request.current_level, request.escalated), (2, 0))


class TestDelegation(ApprovalTestCase):
	def test_delegate_approves_in_window_and_trail_records_on_behalf_of(self):
		make_delegation(fx.HOD, fx.DELEGATE, add_days(today(), -1), add_days(today(), 1))
		_doc, name = self.new_request()
		self.act_as(fx.DELEGATE, approve, name)
		action = self.request(name).actions[-1]
		self.assertEqual(
			(action.action, action.approver, action.on_behalf_of), ("Approve", fx.DELEGATE, fx.HOD)
		)
		self.assertEqual(self.request(name).current_level, 2)

	def test_delegate_cannot_act_outside_the_window(self):
		make_delegation(fx.HOD, fx.DELEGATE, add_days(today(), 1), add_days(today(), 5))
		make_delegation(fx.HOD, fx.DELEGATE, add_days(today(), -9), add_days(today(), -1))
		_doc, name = self.new_request()
		with self.assertRaises(frappe.PermissionError):
			self.act_as(fx.DELEGATE, approve, name)

	def test_delegate_not_permitted_for_the_company_is_refused(self):
		make_delegation(fx.HOD, fx.OTHER_DELEGATE, today(), today())
		_doc, name = self.new_request()
		with self.assertRaises(frappe.PermissionError):
			self.act_as(fx.OTHER_DELEGATE, approve, name)
		self.assertEqual(len(self.request(name).actions), 1)

	def test_delegation_limited_to_other_document_types_does_not_apply(self):
		make_delegation(fx.HOD, fx.DELEGATE, today(), today(), document_types=["ToDo"])
		_doc, name = self.new_request()
		with self.assertRaises(frappe.PermissionError):
			self.act_as(fx.DELEGATE, approve, name)

	def test_delegation_covering_the_document_type_applies(self):
		make_delegation(fx.HOD, fx.DELEGATE, today(), today(), document_types=[fx.DOCTYPE])
		_doc, name = self.new_request()
		self.act_as(fx.DELEGATE, approve, name)
		self.assertEqual(self.request(name).actions[-1].on_behalf_of, fx.HOD)

	def test_principal_cannot_approve_again_after_delegate(self):
		for user in (fx.HOD, fx.DEAN):
			frappe.get_doc("User", user).add_roles("Accounts User")
		fx.make_policy(
			"APR Test Two Of Role", [fx.level("Role", "Accounts User", min_approvals=2)], priority=99
		)
		make_delegation(fx.HOD, fx.DELEGATE, today(), today())
		_doc, name = self.new_request()
		self.act_as(fx.DELEGATE, approve, name)
		with self.assertRaisesRegex(frappe.ValidationError, "already approved"):
			self.act_as(fx.HOD, approve, name)
		self.assertEqual(self.act_as(fx.DEAN, approve, name), "Approved")

	def test_field_approver_can_delegate(self):
		make_delegation(fx.HOD, fx.DELEGATE, today(), today())
		fx.make_policy(
			"APR Test Field", [fx.level("Field", "approver_user"), fx.level("User", fx.DEAN)], priority=99
		)
		_doc, name = self.new_request(approver_user=fx.HOD)
		self.act_as(fx.DELEGATE, approve, name)
		self.assertEqual(self.request(name).current_level, 2)

	def test_delegation_rules(self):
		with self.assertRaises(frappe.ValidationError):
			make_delegation(fx.HOD, fx.HOD, today(), today())
		with self.assertRaises(frappe.ValidationError):
			make_delegation(fx.HOD, fx.DELEGATE, today(), add_days(today(), -1))
		frappe.set_user(fx.OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			make_delegation(fx.HOD, fx.DELEGATE, today(), today())


class TestMyPendingApprovals(ApprovalTestCase):
	def rows_for(self, user, **filters):
		frappe.set_user(user)
		return execute(filters)[1]

	def test_lists_requests_waiting_on_the_user(self):
		_doc, name = self.new_request()
		rows = self.rows_for(fx.HOD)
		self.assertEqual(
			[(r["request"], r["current_level"], r["on_behalf_of"]) for r in rows], [(name, 1, None)]
		)
		self.assertFalse(self.rows_for(fx.DEAN))
		self.assertFalse(self.rows_for(fx.OUTSIDER))

	def test_delegate_sees_requests_on_behalf_of_the_approver(self):
		make_delegation(fx.HOD, fx.DELEGATE, today(), today())
		_doc, name = self.new_request()
		self.assertEqual(
			[(r["request"], r["on_behalf_of"]) for r in self.rows_for(fx.DELEGATE)], [(name, fx.HOD)]
		)

	def test_company_filter(self):
		self.new_request()
		self.assertFalse(self.rows_for(fx.HOD, company=fx.OTHER_COLLEGE))
		self.assertEqual(len(self.rows_for(fx.HOD, company=fx.COLLEGE)), 1)

	def test_requests_of_companies_the_user_is_not_permitted_for_are_hidden(self):
		fx.make_policy("APR Test Other Co", [fx.level("User", fx.HOD)], priority=99, company=fx.OTHER_COLLEGE)
		_doc, name = self.new_request(company=fx.OTHER_COLLEGE)
		self.assertFalse(self.rows_for(fx.HOD))
		with self.assertRaises(frappe.PermissionError):
			self.act_as(fx.HOD, approve, name)
