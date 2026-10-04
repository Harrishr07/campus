"""M17-03 integration tests: approver types (Role, Position, User, Field, Reporting Manager) and
Approval Policy validation."""

import frappe

from campus.campus_platform.approver_resolution import resolve_approvers
from campus.tests import approval_fixtures as fx
from campus.tests.test_approvals import ApprovalTestCase


def make_employee(first_name, user, reports_to=None):
	existing = frappe.db.get_value("Employee", {"user_id": user})
	if existing:
		frappe.db.set_value("Employee", existing, "reports_to", reports_to)
		return existing
	if not frappe.db.exists("Gender", "Female"):
		frappe.get_doc({"doctype": "Gender", "gender": "Female"}).insert()
	return (
		frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": first_name,
				"gender": "Female",
				"date_of_birth": "1985-01-01",
				"date_of_joining": "2020-01-01",
				"company": fx.COLLEGE,
				"user_id": user,
				"reports_to": reports_to,
			}
		)
		.insert()
		.name
	)


class TestApproverTypes(ApprovalTestCase):
	def doc(self, **extra):
		return fx.make_document(10, extra.pop("department", self.department), **extra)

	def test_role_limited_to_users_permitted_for_the_company(self):
		frappe.get_doc("User", fx.CLERK).add_roles("Auditor")
		frappe.get_doc("User", fx.OUTSIDER).add_roles("Auditor")
		frappe.db.delete("User Permission", {"user": fx.OUTSIDER})
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": fx.OUTSIDER,
				"allow": "Company",
				"for_value": fx.OTHER_COLLEGE,
			}
		).insert()
		doc = self.doc()
		limited = resolve_approvers("Role", "Auditor", doc, limit_to_company=True)
		self.assertIn(fx.CLERK, limited)
		self.assertNotIn(fx.OUTSIDER, limited)
		self.assertIn(fx.OUTSIDER, resolve_approvers("Role", "Auditor", doc))

	def test_position_scoped_by_a_document_field(self):
		self.assertEqual(resolve_approvers("Position", "HOD", self.doc(), scope_field="department"), [fx.HOD])
		other = fx.make_department("Approval Test Empty", fx.COLLEGE)
		self.assertEqual(
			resolve_approvers("Position", "HOD", self.doc(department=other), scope_field="department"), []
		)

	def test_user_and_disabled_user(self):
		self.assertEqual(resolve_approvers("User", fx.DEAN, self.doc()), [fx.DEAN])
		frappe.db.set_value("User", fx.DEAN, "enabled", 0)
		self.addCleanup(frappe.db.set_value, "User", fx.DEAN, "enabled", 1)
		self.assertEqual(resolve_approvers("User", fx.DEAN, self.doc()), [])

	def test_field_holding_a_user(self):
		self.assertEqual(
			resolve_approvers("Field", "approver_user", self.doc(approver_user=fx.PRINCIPAL)), [fx.PRINCIPAL]
		)
		self.assertEqual(resolve_approvers("Field", "approver_user", self.doc()), [])

	def test_reporting_manager_of_owner_or_named_employee(self):
		manager = make_employee("Apr Manager", fx.PRINCIPAL)
		staff = make_employee("Apr Staff", fx.CLERK, reports_to=manager)
		frappe.set_user(fx.CLERK)
		owned = frappe.get_doc({"doctype": fx.DOCTYPE, "title": "x", "company": fx.COLLEGE}).insert(
			ignore_permissions=True
		)
		frappe.set_user("Administrator")
		self.assertEqual(resolve_approvers("Reporting Manager", None, owned), [fx.PRINCIPAL])
		self.assertEqual(
			resolve_approvers("Reporting Manager", "employee", self.doc(employee=staff)), [fx.PRINCIPAL]
		)
		self.assertEqual(resolve_approvers("Reporting Manager", None, self.doc()), [])

	def test_unknown_type_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			resolve_approvers("Committee", "x", self.doc())


class TestPolicyValidation(ApprovalTestCase):
	def test_document_type_must_use_the_engine(self):
		with self.assertRaisesRegex(frappe.ValidationError, "approval engine"):
			frappe.get_doc(
				{"doctype": "Approval Policy", "policy_name": "APR Test Bad", "document_type": "Program Enrollment",
				 "levels": [fx.level("User", fx.HOD)]}
			).insert()  # fmt: skip

	def test_invalid_condition_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Condition"):
			fx.make_policy("APR Test Bad", [fx.level("User", fx.HOD)], condition="doc.amount >")

	def test_unknown_names_and_fields_are_refused(self):
		for bad in (
			fx.level("Position", "NO-SUCH-POSITION"),
			fx.level("Role", "No Such Role"),
			fx.level("Field", "no_such_field"),
			fx.level("User", fx.HOD, can_edit_fields="amount, nope"),
			fx.level("User", fx.HOD, escalate_to_type="User", escalate_to="nobody@example.com"),
		):
			with self.assertRaises(frappe.ValidationError):
				fx.make_policy("APR Test Bad", [bad])

	def test_levels_are_frozen_while_requests_are_pending(self):
		self.new_request()
		policy = frappe.get_doc("Approval Policy", fx.BIG)
		policy.levels[0].approver = "PRINCIPAL"
		with self.assertRaisesRegex(frappe.ValidationError, "pending"):
			policy.save()
		policy.reload()
		policy.priority = 11
		policy.save()
