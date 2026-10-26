"""NFR Mandatory approval (BRD 16.2, roadmap R-07): a document type listed in Campus Settings > Approval Required
DocTypes cannot be submitted when no Approval Policy matches; unlisted document types keep submitting directly."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, now_datetime

from campus.campus_platform import mandatory_approval
from campus.campus_platform.approvals import approve, reject, request_approval
from campus.tests import approval_fixtures as fx
from campus.tests.factories import make_user
from campus.tests.test_approvals import ApprovalTestCase

REFUSAL = "No approval policy is configured for Approval Test Document"
SYSTEM_MANAGER = "apr-sysmgr@example.com"


class TestMandatoryApproval(ApprovalTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.db.after_rollback.reset)  # a refusal's flag never commits inside a test
		self.unlist(fx.DOCTYPE)

	def require(self, doctype):
		row = frappe.get_doc(
			{
				"doctype": mandatory_approval.ROW_DOCTYPE,
				"parent": "Campus Settings",
				"parenttype": "Campus Settings",
				"parentfield": mandatory_approval.SETTINGS_FIELD,
				"document_type": doctype,
				"idx": 99,
			}
		)
		row.db_insert()
		self.addCleanup(frappe.db.delete, mandatory_approval.ROW_DOCTYPE, {"name": row.name})

	def unlist(self, doctype):
		frappe.db.delete(
			mandatory_approval.ROW_DOCTYPE, {"parenttype": "Campus Settings", "document_type": doctype}
		)

	def test_a_listed_doctype_without_a_matching_policy_is_refused(self):
		self.require(fx.DOCTYPE)
		doc = fx.make_document(500, self.department)  # below every policy condition
		with self.assertRaisesRegex(frappe.ValidationError, REFUSAL) as caught:
			request_approval(fx.DOCTYPE, doc.name)
		self.assertIn("ask the administrator", str(caught.exception))
		with self.assertRaisesRegex(frappe.ValidationError, REFUSAL):
			doc.reload().submit()
		self.assertEqual(frappe.db.get_value(fx.DOCTYPE, doc.name, "docstatus"), 0)
		self.assertFalse(frappe.db.exists("Approval Request", {"reference_name": doc.name}))

	def test_a_listed_doctype_with_a_matching_policy_goes_through_approval(self):
		self.require(fx.DOCTYPE)
		doc, name = self.new_request(5000)
		self.assertEqual(self.request(name).policy, fx.SMALL)
		self.assertEqual(self.act_as(fx.CLERK, approve, name), "Approved")
		self.assertEqual(doc.reload().docstatus, 1)

	def test_an_unlisted_doctype_without_a_policy_still_submits_directly(self):
		doc, name = self.new_request(500)
		self.assertIsNone(name)
		self.assertEqual(doc.reload().docstatus, 1)
		plain = fx.make_document(600, self.department)
		plain.submit()
		self.assertEqual(plain.docstatus, 1)

	def test_an_amended_copy_of_a_cancelled_listed_document_without_a_policy_is_refused(self):
		self.require(fx.DOCTYPE)
		doc, name = self.new_request(5000)
		self.act_as(fx.CLERK, approve, name)
		doc.reload().cancel()
		self.disable_policies()
		amended = frappe.copy_doc(doc)
		amended.update({"amended_from": doc.name, "docstatus": 0})
		amended.insert()
		with self.assertRaisesRegex(frappe.ValidationError, REFUSAL):
			request_approval(fx.DOCTYPE, amended.name)
		with self.assertRaisesRegex(frappe.ValidationError, REFUSAL):
			amended.reload().submit()
		self.assertEqual(frappe.db.get_value(fx.DOCTYPE, amended.name, "docstatus"), 0)

	def test_a_rejected_document_is_refused_when_its_policy_was_disabled_before_resubmission(self):
		self.require(fx.DOCTYPE)
		doc, name = self.new_request(5000)
		self.assertEqual(self.act_as(fx.CLERK, reject, name, "No"), "Rejected")
		self.disable_policies()
		with self.assertRaisesRegex(frappe.ValidationError, REFUSAL):
			request_approval(fx.DOCTYPE, doc.name)
		with self.assertRaisesRegex(frappe.ValidationError, REFUSAL):
			doc.reload().submit()
		self.assertEqual(frappe.db.get_value(fx.DOCTYPE, doc.name, "docstatus"), 0)

	def disable_policies(self):
		frappe.db.set_value("Approval Policy", {"document_type": fx.DOCTYPE}, "enabled", 0)

	def test_settings_refuse_a_doctype_outside_the_approval_engine(self):
		settings = frappe.get_doc("Campus Settings")
		settings.append(mandatory_approval.SETTINGS_FIELD, {"document_type": "ToDo"})
		with self.assertRaisesRegex(frappe.ValidationError, "ToDo.* does not use the approval engine"):
			settings.validate_approval_required_doctypes()


class TestFlaggedForConfiguration(ApprovalTestCase):
	"""A refusal rolls its transaction back; the flag (Error Log + System Manager alert) is written after the rollback."""

	def setUp(self):
		self.addCleanup(self.delete_flags)  # Error Log is MyISAM: its rows outlive every rollback
		frappe.db.savepoint("flag_test")  # the runner commits at the end; leave no alert behind
		self.addCleanup(frappe.db.rollback, save_point="flag_test")
		super().setUp()
		self.addCleanup(frappe.db.after_rollback.reset)
		self.delete_flags()
		make_user(SYSTEM_MANAGER, [])
		frappe.get_doc("User", SYSTEM_MANAGER).add_roles("System Manager")
		frappe.db.delete("Notification Log", {"for_user": SYSTEM_MANAGER})

	def delete_flags(self):
		frappe.db.delete("Error Log", {"method": ["like", "Approval policy missing for %"]})

	def refuse(self, doctype, user=fx.CLERK):
		doc = frappe._dict(doctype=doctype, name="X")
		frappe.db.savepoint("refused_request")
		frappe.set_user(user)
		try:
			with patch.object(mandatory_approval, "approval_required", return_value=True):
				with self.assertRaisesRegex(frappe.ValidationError, "No approval policy is configured"):
					mandatory_approval.refuse_without_policy(doc)
		finally:
			frappe.set_user("Administrator")
		frappe.db.rollback(save_point="refused_request")  # the request fails and rolls back

	def run_after_rollback(self):
		with patch.object(frappe.db, "commit") as commit:
			frappe.db.after_rollback.run()
		return commit

	def flags(self, doctype=None):
		title = (
			f"Approval policy missing for {doctype}" if doctype else ["like", "Approval policy missing for %"]
		)
		return frappe.get_all(
			"Error Log",
			filters={"method": title},
			fields=["method", "error", "reference_doctype", "reference_name"],
		)

	def alerts(self):
		return frappe.get_all(
			"Notification Log",
			filters={"for_user": SYSTEM_MANAGER},
			fields=["subject", "document_type", "document_name"],
		)

	def test_a_refusal_is_flagged_after_its_rollback_with_doctype_and_user(self):
		self.refuse(fx.DOCTYPE)
		self.assertFalse(self.flags())  # nothing is written until the refused transaction has rolled back
		self.run_after_rollback().assert_called_once_with()
		(flag,) = self.flags(fx.DOCTYPE)
		self.assertIn(fx.DOCTYPE, flag.error)
		self.assertIn(fx.CLERK, flag.error)
		self.assertEqual((flag.reference_doctype, flag.reference_name), ("DocType", fx.DOCTYPE))
		(alert,) = self.alerts()
		self.assertIn(fx.DOCTYPE, alert.subject)
		self.assertEqual((alert.document_type, alert.document_name), ("Campus Settings", "Campus Settings"))

	def test_a_doctype_is_flagged_once_a_day(self):
		self.refuse(fx.DOCTYPE)
		self.run_after_rollback()
		self.refuse(fx.DOCTYPE, user=fx.HOD)
		self.run_after_rollback().assert_not_called()
		self.assertEqual(len(self.flags(fx.DOCTYPE)), 1)
		self.assertEqual(len(self.alerts()), 1)
		self.refuse("Fee Refund")
		self.run_after_rollback().assert_called_once_with()
		self.assertEqual(len(self.flags("Fee Refund")), 1)
		self.assertEqual(len(self.alerts()), 2)

	def test_a_failing_flag_never_breaks_the_rollback_or_later_callbacks(self):
		self.refuse(fx.DOCTYPE)
		later = []
		frappe.db.after_rollback.add(lambda: later.append(True))
		with patch.object(
			mandatory_approval, "enqueue_create_notification", side_effect=RuntimeError("redis down")
		):
			self.run_after_rollback()  # must not raise
		self.assertEqual(later, [True])

	def test_yesterdays_flag_does_not_silence_today(self):
		self.refuse(fx.DOCTYPE)
		self.run_after_rollback()
		frappe.db.set_value(
			"Error Log",
			{"method": f"Approval policy missing for {fx.DOCTYPE}"},
			"creation",
			add_days(now_datetime(), -1),
		)
		self.refuse(fx.DOCTYPE)
		self.run_after_rollback().assert_called_once_with()
		self.assertEqual(len(self.flags(fx.DOCTYPE)), 2)

	def test_the_engine_refusal_registers_the_flag(self):
		self.require_listed()
		doc = fx.make_document(500, self.department)
		with self.assertRaisesRegex(frappe.ValidationError, REFUSAL):
			request_approval(fx.DOCTYPE, doc.name)
		self.run_after_rollback()
		self.assertEqual(len(self.flags(fx.DOCTYPE)), 1)

	def require_listed(self):
		patcher = patch.object(mandatory_approval, "approval_required", return_value=True)
		patcher.start()
		self.addCleanup(patcher.stop)


class TestSeedList(ApprovalTestCase):
	def test_the_seed_lists_existing_engine_doctypes_not_yet_listed(self):
		expected = [
			"Result Ratification", "Fee Refund", "Fee Concession", "Scholarship Application", "Rejoin Application",
			"Examiner Remuneration Claim", "Utilisation Certificate", "Credit Recognition",
			"Consultancy Revenue Share",
		]  # fmt: skip
		self.assertEqual(list(mandatory_approval.MANDATORY_APPROVAL_DOCTYPES), expected)
		self.assertEqual(mandatory_approval.missing_doctypes(set()), expected)
		self.assertEqual(
			mandatory_approval.missing_doctypes({"Fee Refund", "Fee Concession"}),
			[d for d in expected if not d.startswith("Fee")],
		)
		for doctype in expected:
			self.assertTrue(mandatory_approval.uses_approval_engine(doctype), doctype)

	def test_certificate_requests_keep_their_own_per_type_gate(self):
		self.assertNotIn("Certificate Request", mandatory_approval.MANDATORY_APPROVAL_DOCTYPES)

	def test_the_migrated_site_lists_the_seed(self):
		listed = set(
			frappe.get_all(
				mandatory_approval.ROW_DOCTYPE, {"parenttype": "Campus Settings"}, pluck="document_type"
			)
		)
		self.assertLessEqual(set(mandatory_approval.MANDATORY_APPROVAL_DOCTYPES), listed)

	def test_a_doctype_outside_the_engine_is_not_seeded(self):
		self.assertFalse(mandatory_approval.uses_approval_engine("ToDo"))
		self.assertTrue(mandatory_approval.uses_approval_engine(fx.DOCTYPE))
