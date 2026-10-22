"""NFR Mandatory approval (BRD 16.2, roadmap R-07): a document type listed in Campus Settings > Approval Required
DocTypes cannot be submitted when no Approval Policy matches; unlisted document types keep submitting directly."""

import frappe

from campus.campus_platform import mandatory_approval
from campus.campus_platform.approvals import approve, request_approval
from campus.tests import approval_fixtures as fx
from campus.tests.test_approvals import ApprovalTestCase

REFUSAL = "No approval policy is configured for Approval Test Document"


class TestMandatoryApproval(ApprovalTestCase):
	def setUp(self):
		super().setUp()
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
		frappe.db.delete(mandatory_approval.ROW_DOCTYPE, {"parenttype": "Campus Settings", "document_type": doctype})

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

	def test_settings_refuse_a_doctype_outside_the_approval_engine(self):
		settings = frappe.get_doc("Campus Settings")
		settings.append(mandatory_approval.SETTINGS_FIELD, {"document_type": "ToDo"})
		with self.assertRaisesRegex(frappe.ValidationError, "ToDo.* does not use the approval engine"):
			settings.validate_approval_required_doctypes()


class TestSeedList(ApprovalTestCase):
	def test_the_seed_lists_existing_engine_doctypes_not_yet_listed(self):
		expected = [
			"Result Ratification", "Fee Refund", "Fee Concession", "Scholarship Application", "Rejoin Application",
			"Examiner Remuneration Claim", "Utilisation Certificate",
		]  # fmt: skip
		self.assertEqual(list(mandatory_approval.MANDATORY_APPROVAL_DOCTYPES), expected)
		self.assertEqual(mandatory_approval.missing_doctypes(set()), expected)
		self.assertEqual(mandatory_approval.missing_doctypes({"Fee Refund", "Fee Concession"}), [d for d in expected if not d.startswith("Fee")])
		for doctype in expected:
			self.assertTrue(mandatory_approval.uses_approval_engine(doctype), doctype)

	def test_certificate_requests_keep_their_own_per_type_gate(self):
		self.assertNotIn("Certificate Request", mandatory_approval.MANDATORY_APPROVAL_DOCTYPES)

	def test_the_migrated_site_lists_the_seed(self):
		listed = set(frappe.get_all(mandatory_approval.ROW_DOCTYPE, {"parenttype": "Campus Settings"}, pluck="document_type"))
		self.assertLessEqual(set(mandatory_approval.MANDATORY_APPROVAL_DOCTYPES), listed)

	def test_a_doctype_outside_the_engine_is_not_seeded(self):
		self.assertFalse(mandatory_approval.uses_approval_engine("ToDo"))
		self.assertTrue(mandatory_approval.uses_approval_engine(fx.DOCTYPE))
