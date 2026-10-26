"""M05-14 tests: correction / reissue of an issued certificate - approval, supersession chain, verification, TC status,
print marking, fee."""

import frappe
from frappe.utils import today
from frappe.website.serve import get_response

from campus.campus_platform.approval_engine import find_policy
from campus.campus_platform.verification import public_lookup, verify
from campus.student_services import certificate_fee
from campus.tests.test_certificates import BONAFIDE, COLLEGE, TRANSFER, CertificateFixture
from campus.tests.test_verification import request_as

EVIDENCE = "/private/files/proof.pdf"
CORRECTION, DAMAGED, LOST = "Correction of Particulars", "Damaged", "Lost"
SEEDED = "Certificate Reissue"


class ReissueFixture(CertificateFixture):
	drop_seeded_policy = (
		True  # the seeded policy needs the college's Principal; tests approve through the fixture's policy
	)

	def setUp(self):
		super().setUp()
		if self.drop_seeded_policy:
			frappe.db.delete("Approval Level", {"parent": SEEDED})
			frappe.db.delete("Approval Policy", {"name": SEEDED})

	def issue(self, student=None, certificate_type=BONAFIDE, **values):
		return self.approve_request(self.request(student or self.a, certificate_type, **values))

	def reissue_draft(self, original, reason=DAMAGED, **values):
		values = {"supersedes": original.name, "reissue_reason": reason, **values}
		if reason == CORRECTION:
			values.setdefault("evidence", EVIDENCE)
		if reason == LOST:
			values.setdefault("evidence", EVIDENCE)
			values.setdefault("reference_note", "FIR 42/2026")
		return self.request(original.student, original.certificate_type, **values)

	def reissue(self, original, reason=DAMAGED, **values):
		return self.approve_request(self.reissue_draft(original, reason, **values))

	def tc(self, **values):
		return self.issue(self.a, TRANSFER, reason_for_leaving="Migrating to another city", **values)


class TestReissueApproval(ReissueFixture):
	def test_a_reissue_needs_approval_even_when_its_type_needs_none(self):
		frappe.db.set_value("Certificate Type", BONAFIDE, "needs_approval", 0)
		original = self.request(self.a)
		original.submit()  # issued without approval
		draft = self.reissue_draft(original, CORRECTION)
		self.assertEqual(draft.needs_approval, 1)
		with self.assertRaisesRegex(frappe.ValidationError, "needs approval"):
			draft.submit()
		draft.reload()
		self.assertEqual(self.approve_request(draft).docstatus, 1)


class TestNoPolicy(ReissueFixture):
	def test_a_reissue_with_no_matching_policy_says_so(self):
		from campus.campus_platform.approvals import request_approval

		original = self.issue()
		draft = self.reissue_draft(original)
		frappe.db.set_value("Approval Policy", {"document_type": "Certificate Request"}, "enabled", 0)
		with self.assertRaisesRegex(
			frappe.ValidationError, "No approval policy is configured for Certificate Reissue"
		):
			request_approval("Certificate Request", draft.name)


class TestSeededPolicy(ReissueFixture):
	drop_seeded_policy = False

	def test_the_seeded_policy_takes_a_reissue_and_leaves_other_requests_alone(self):
		if not frappe.db.exists("Approval Policy", SEEDED):
			self.skipTest("no PRINCIPAL position on this site")
		original = self.issue()
		self.assertEqual(find_policy(self.reissue_draft(original)).name, SEEDED)
		self.assertEqual(find_policy(self.request(self.b)).name, "CRT Test Policy")


class TestReissueRules(ReissueFixture):
	def test_the_original_must_be_an_issued_current_certificate_of_the_same_student_and_type(self):
		cancelled = self.issue(self.a)
		cancelled.cancel()
		with self.assertRaisesRegex(frappe.ValidationError, "not an issued certificate|cancelled document"):
			self.reissue_draft(cancelled)
		other = self.issue(self.b)
		with self.assertRaisesRegex(frappe.ValidationError, "same student"):
			self.request(self.a, BONAFIDE, supersedes=other.name, reissue_reason=DAMAGED)
		original = self.issue(self.c)
		self.reissue(original)
		with self.assertRaisesRegex(frappe.ValidationError, "already superseded"):
			self.reissue_draft(original)

	def test_evidence_and_reference_are_required_and_private(self):
		original = self.issue()
		with self.assertRaisesRegex(frappe.ValidationError, "Evidence|evidence"):
			self.reissue_draft(original, CORRECTION, evidence=None)
		with self.assertRaisesRegex(frappe.ValidationError, "FIR|Evidence|evidence"):
			self.reissue_draft(original, LOST, reference_note=" ")
		for path in (
			"/files/proof.pdf",
			"/private/../files/proof.pdf",
			"/private//../files/proof.pdf",
			"/private/",
		):
			with self.assertRaisesRegex(frappe.ValidationError, "private"):
				self.reissue_draft(original, LOST, evidence=path)
		self.assertTrue(self.reissue_draft(original, LOST).name)

	def test_the_chain_keeps_every_certificate_and_only_the_last_is_current(self):
		first = self.issue()
		second = self.reissue(first, CORRECTION)
		third = self.reissue(second, LOST)
		numbers = {first.certificate_number, second.certificate_number, third.certificate_number}
		self.assertEqual(len(numbers), 3)
		superseded_by = {
			name: frappe.db.get_value("Certificate Request", name, "superseded_by")
			for name in (first.name, second.name, third.name)
		}
		self.assertEqual(superseded_by, {first.name: second.name, second.name: third.name, third.name: None})
		for name in (first.name, second.name, third.name):
			self.assertEqual(
				frappe.db.get_value("Certificate Request", name, "docstatus"), 1
			)  # never deleted or cancelled
		self.assertEqual(frappe.get_doc("Certificate Request", third.name).supersedes, second.name)

	def test_a_superseded_original_cannot_be_cancelled_until_the_reissue_is(self):
		first = self.issue()
		second = self.reissue(first)
		frappe.db.savepoint("refused_cancel")  # a refused cancel rolls back in a request; in a test, by hand
		with self.assertRaisesRegex(frappe.ValidationError, "Cancel .* first"):
			first.cancel()
		frappe.db.rollback(save_point="refused_cancel")
		second.cancel()
		first.reload()
		self.assertFalse(first.superseded_by)
		self.assertEqual(verify(first.verification_code).status, "Valid")
		self.assertEqual(verify(second.verification_code).status, "Revoked")
		first.cancel()  # current again

	def test_cancelling_a_reissue_lets_the_original_be_reissued_again(self):
		first = self.issue()
		self.reissue(first).cancel()
		self.assertTrue(self.reissue(first, CORRECTION).name)


class TestReissueVerification(ReissueFixture):
	def test_verification_shows_the_original_as_superseded_and_points_to_the_current_one(self):
		first = self.issue()
		self.assertEqual(verify(first.verification_code).status, "Valid")
		second = self.reissue(first, CORRECTION)
		found = verify(first.verification_code)
		self.assertEqual((found.status, found.superseded_by_code), ("Superseded", second.verification_code))
		self.assertEqual(verify(second.verification_code).status, "Valid")
		public = public_lookup(first.verification_code)
		self.assertEqual(
			(public.status, public.superseded_by_code, public.details),
			("Superseded", second.verification_code, []),
		)

	def test_the_public_page_renders_the_superseded_state_and_the_link(self):
		first = self.issue()
		second = self.reissue(first)
		self.addCleanup(setattr, frappe.local, "form_dict", frappe.local.form_dict)
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		request_as("10.0.0.23", f"/verify/{first.verification_code}")
		frappe.local.form_dict = frappe._dict()
		frappe.local.response = frappe._dict()
		html = get_response(f"verify/{first.verification_code}").get_data(as_text=True)
		self.assertIn("Superseded", html)
		self.assertIn(f"/verify/{second.verification_code}", html)


class TestReissuedTransferCertificate(ReissueFixture):
	def transitions(self):
		return frappe.db.count("Lifecycle Transition", {"student": self.a})

	def test_a_reissued_tc_does_not_run_the_status_change_again(self):
		original = self.tc()
		self.assertEqual(frappe.db.get_value("Student", self.a, "oc_academic_status"), "Withdrawn")
		before = self.transitions()
		duplicate = self.reissue(original, DAMAGED)
		self.assertEqual(self.transitions(), before)  # no second transition
		student = frappe.get_doc("Student", self.a)
		self.assertEqual(student.oc_academic_status, "Withdrawn")
		self.assertEqual(student.leaving_certificate_number, duplicate.certificate_number)
		self.assertEqual(
			(duplicate.leaving_date, duplicate.reason_for_leaving),
			(original.leaving_date, original.reason_for_leaving),
		)

	def test_a_tc_correction_updates_the_leaving_particulars_without_a_transition(self):
		original = self.tc()
		before = self.transitions()
		corrected = self.reissue(original, CORRECTION, reason_for_leaving="Joining another college")
		self.assertEqual(self.transitions(), before)
		student = frappe.get_doc("Student", self.a)
		self.assertEqual(
			(student.leaving_certificate_number, student.reason_for_leaving),
			(corrected.certificate_number, "Joining another college"),
		)

	def test_a_reissue_is_not_blocked_by_dues_that_arose_after_the_tc(self):
		original = self.tc()
		self.owe(self.a, COLLEGE)
		self.assertTrue(self.reissue(original).name)

	def test_cancelling_the_reissue_restores_the_original_tc_without_touching_the_status(self):
		original = self.tc()
		duplicate = self.reissue(original, CORRECTION, reason_for_leaving="Joining another college")
		before = self.transitions()
		duplicate.cancel()
		self.assertEqual(self.transitions(), before)
		student = frappe.get_doc("Student", self.a)
		self.assertEqual(student.oc_academic_status, "Withdrawn")
		self.assertEqual(
			(student.leaving_certificate_number, student.reason_for_leaving),
			(original.certificate_number, "Migrating to another city"),
		)
		original.reload()
		original.cancel()  # now current: the L-01 reversal still works
		self.assertEqual(frappe.db.get_value("Student", self.a, "oc_academic_status"), "Active")


class TestReissuePrintAndFee(ReissueFixture):
	def html(self, doc):
		return frappe.get_print("Certificate Request", doc.name, "Bonafide Certificate")

	def test_a_duplicate_prints_duplicate_and_a_correction_prints_reissued(self):
		original = self.issue()
		self.assertNotIn("oc-reissue-mark", self.html(original))
		duplicate = self.reissue(original, DAMAGED)
		html = self.html(duplicate)
		self.assertIn("DUPLICATE", html)
		self.assertIn(f"In place of No. {original.certificate_number}", html)
		self.assertIn("REISSUED", self.html(self.reissue(duplicate, CORRECTION)))

	def test_the_marking_can_be_switched_off_for_a_type(self):
		frappe.db.set_value("Certificate Type", BONAFIDE, "mark_reissues", 0)
		duplicate = self.reissue(self.issue())
		self.assertFalse(duplicate.marking)
		self.assertNotIn("oc-reissue-mark", self.html(duplicate))

	def test_the_duplicate_fee_is_raised_once_and_a_correction_is_free(self):
		frappe.db.set_value("Certificate Type", BONAFIDE, {"fee_amount": 100, "reissue_fee": 40})
		original = self.issue()
		duplicate = self.reissue(original, DAMAGED)
		self.assertEqual(duplicate.fee_amount, 40)
		certificate_fee.raise_fee(duplicate.name)
		certificate_fee.raise_fee(duplicate.name)  # idempotent
		duplicate.reload()
		invoice = frappe.get_doc("Sales Invoice", duplicate.fee_invoice)
		self.assertEqual((invoice.grand_total, invoice.items[0].item_code), (40, "Certificate"))
		self.assertEqual(
			frappe.db.count("Sales Invoice", {"student": self.a, "name": duplicate.fee_invoice}), 1
		)
		corrected = self.reissue(duplicate, CORRECTION)
		self.assertEqual(corrected.fee_amount, 0)
		certificate_fee.raise_fee(corrected.name)
		self.assertFalse(frappe.db.get_value("Certificate Request", corrected.name, "fee_invoice"))
