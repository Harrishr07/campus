"""M17-04 tests: issue, verify, revoke, QR macro, public page, rate limit, hash stability."""

import contextlib
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import today
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from campus.campus_platform import verification
from campus.campus_platform.verification import (
	CODE_ALPHABET,
	CODE_LENGTH,
	issue,
	mask_name,
	oc_qr_block,
	revoke,
	verify,
)
from campus.tests.factories import make_company, make_user
from campus.tests.utils import CampusTestCase

COLLEGE = "Verify Test College"
CERT_FORMAT = "OC Verify Test Certificate"
MANAGER = "verify-manager@example.com"
CLERK = "verify-clerk@example.com"


def make_certificate(title="Rahul Kumar"):
	return frappe.get_doc({"doctype": "Approval Test Document", "title": title, "company": COLLEGE}).insert()


def make_print_format():
	if frappe.db.exists("Print Format", CERT_FORMAT):
		return
	frappe.get_doc(
		{
			"doctype": "Print Format",
			"name": CERT_FORMAT,
			"doc_type": "Approval Test Document",
			"print_format_type": "Jinja",
			"custom_format": 1,
			"standard": "No",
			"html": "<h1>Certificate for {{ doc.title }}</h1>{{ oc_qr_block(doc) }}",
		}
	).insert()


def request_as(ip, path="/verify/x", method="GET"):
	frappe.local.request = Request(EnvironBuilder(path=path, method=method).get_environ())
	frappe.local.request_ip = ip


class VerificationTestCase(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, "VTC")
		make_print_format()
		for user, role in ((MANAGER, verification.VERIFICATION_ROLE), (CLERK, "Academics User")):
			make_user(user, [COLLEGE])
			frappe.get_doc("User", user).add_roles(role)

	def tearDown(self):
		frappe.set_user("Administrator")
		with contextlib.suppress(AttributeError):
			del frappe.local.request


class TestIssue(VerificationTestCase):
	def test_issue_stores_hash_code_and_holder(self):
		cert = make_certificate()
		record = issue(cert, CERT_FORMAT)
		self.assertEqual(len(record.code), CODE_LENGTH)
		self.assertTrue(set(record.code) <= set(CODE_ALPHABET))
		self.assertEqual(record.status, "Valid")
		self.assertEqual(record.company, COLLEGE)
		self.assertEqual(record.holder_name, "Rahul Kumar")
		self.assertEqual((record.reference_doctype, record.reference_name), (cert.doctype, cert.name))
		self.assertRegex(record.sha256, r"^[0-9a-f]{64}$")

	def test_alphabet_has_no_ambiguous_characters(self):
		self.assertFalse(set("0O1IL") & set(CODE_ALPHABET))

	def test_reissue_creates_new_code_and_keeps_history(self):
		cert = make_certificate()
		first, second = issue(cert, CERT_FORMAT), issue(cert, CERT_FORMAT)
		self.assertNotEqual(first.code, second.code)
		self.assertTrue(frappe.db.exists("Verifiable Document", first.code))

	def test_code_collision_is_retried(self):
		cert = make_certificate()
		taken = issue(cert, CERT_FORMAT).code
		fresh = "ABCDEFGHJK"
		with patch.object(verification.secrets, "choice", side_effect=list(taken + fresh)):
			self.assertEqual(verification.new_code(), fresh)

	def test_same_render_gives_same_hash(self):
		cert = make_certificate()
		render = lambda: frappe.get_print(cert.doctype, cert.name, CERT_FORMAT)  # noqa: E731
		self.assertEqual(render(), render())
		first = issue(cert, CERT_FORMAT)
		rendered = verification.render_for_hash(cert, CERT_FORMAT)
		self.assertEqual(first.sha256, hashlib.sha256(rendered.encode()).hexdigest())
		# the second issue's render could carry the first QR; the hash must not depend on it
		self.assertEqual(first.sha256, issue(cert, CERT_FORMAT).sha256)

	def test_changed_document_changes_hash(self):
		cert = make_certificate()
		before = issue(cert, CERT_FORMAT).sha256
		cert.title = "Someone Else"
		cert.save()
		self.assertNotEqual(before, issue(cert, CERT_FORMAT).sha256)

	def test_stored_fields_cannot_be_edited(self):
		record = issue(make_certificate(), CERT_FORMAT)
		record.sha256 = "0" * 64
		self.assertRaises(frappe.CannotChangeConstantError, record.save)


class TestHolderAndMask(VerificationTestCase):
	def test_holder_name_resolver(self):
		self.assertEqual(verification.holder_name(frappe._dict(name="X1", student_name=" Asha Rao ")), "Asha Rao")
		self.assertEqual(verification.holder_name(frappe._dict(name="X1", employee_name="E One")), "E One")
		self.assertEqual(verification.holder_name(frappe._dict(name="X1", student_name="", title="T")), "T")
		self.assertEqual(verification.holder_name(frappe._dict(name="X1")), "X1")

	def test_mask(self):
		self.assertEqual(mask_name("Rahul Kumar"), "R**** K****")
		self.assertEqual(mask_name("Priya"), "P****")
		self.assertEqual(mask_name(""), "")


class TestVerifyAndRevoke(VerificationTestCase):
	def test_verify_known_and_unknown(self):
		record = issue(make_certificate(), CERT_FORMAT)
		found = verify(record.code.lower())
		self.assertEqual((found.code, found.status, found.company), (record.code, "Valid", COLLEGE))
		self.assertIsNone(verify("NOSUCHCODE"))
		self.assertIsNone(verify(""))
		self.assertIsNone(verify(None))

	def test_revoke_by_system_manager_records_who_when_why(self):
		record = issue(make_certificate(), CERT_FORMAT)
		revoke(record.code, "Issued in error")
		found = verify(record.code)
		self.assertEqual(found.status, "Revoked")
		self.assertEqual(found.revocation_reason, "Issued in error")
		self.assertTrue(found.revoked_on)
		self.assertEqual(frappe.db.get_value("Verifiable Document", record.name, "revoked_by"), "Administrator")

	def test_verification_manager_can_revoke_clerk_cannot(self):
		record = issue(make_certificate(), CERT_FORMAT)
		frappe.set_user(CLERK)
		self.assertRaises(frappe.PermissionError, revoke, record.code, "no")
		frappe.set_user(MANAGER)
		revoke(record.name, "Duplicate")
		self.assertEqual(verify(record.code).status, "Revoked")

	def test_revoke_needs_reason_and_only_once(self):
		record = issue(make_certificate(), CERT_FORMAT)
		self.assertRaises(frappe.ValidationError, revoke, record.code, "  ")
		revoke(record.code, "Because")
		self.assertRaises(frappe.ValidationError, revoke, record.code, "Again")

	def test_revoke_unknown_code(self):
		self.assertRaises(frappe.DoesNotExistError, revoke, "NOSUCHCODE", "x")


class TestQrBlock(VerificationTestCase):
	def test_nothing_before_issue_and_no_side_effects(self):
		cert = make_certificate()
		self.assertEqual(oc_qr_block(cert), "")
		html = frappe.get_print(cert.doctype, cert.name, CERT_FORMAT)
		self.assertNotIn("oc-qr-block", html)
		self.assertFalse(frappe.db.exists("Verifiable Document", {"reference_name": cert.name}))

	def test_print_format_shows_qr_code_and_url_after_issue(self):
		cert = make_certificate()
		record = issue(cert, CERT_FORMAT)
		html = frappe.get_print(cert.doctype, cert.name, CERT_FORMAT)
		self.assertIn("data:image/png;base64,", html)
		self.assertIn(record.code, html)
		self.assertIn(f"/verify/{record.code}", html)

	def test_uses_latest_issue(self):
		cert = make_certificate()
		issue(cert, CERT_FORMAT)
		latest = issue(cert, CERT_FORMAT)
		self.assertIn(latest.code, oc_qr_block(cert))

	def test_base_url_setting_with_fallback(self):
		get_single_value = "frappe.db.get_single_value"
		with patch(get_single_value, return_value=None):
			self.assertEqual(verification.verification_url("ABC"), f"{frappe.utils.get_url()}/verify/ABC")
		with patch(get_single_value, return_value="https://verify.example.edu/"):
			self.assertEqual(verification.verification_url("ABC"), "https://verify.example.edu/verify/ABC")


class TestPublicPage(VerificationTestCase):
	def setUp(self):
		frappe.cache.delete_keys("rl:*")

	def render(self, code):
		from frappe.website.serve import get_response

		frappe.set_user("Guest")
		request_as("10.0.0.9", f"/verify/{code}")
		frappe.local.form_dict = frappe._dict()
		frappe.local.response = frappe._dict()
		return get_response(f"verify/{code}")

	def test_valid_page_shows_masked_details(self):
		record = issue(make_certificate("Rahul Kumar"), CERT_FORMAT)
		response = self.render(record.code)
		body = response.get_data(as_text=True)
		self.assertEqual(response.status_code, 200)
		self.assertIn("R**** K****", body)
		self.assertNotIn("Rahul", body)
		self.assertIn(COLLEGE, body)
		self.assertIn("Approval Test Document", body)
		self.assertIn("Valid", body)

	def test_revoked_page_shows_date_and_reason(self):
		record = issue(make_certificate(), CERT_FORMAT)
		revoke(record.code, "Marks corrected")
		body = self.render(record.code).get_data(as_text=True)
		self.assertIn("Revoked", body)
		self.assertIn("Marks corrected", body)
		self.assertIn(frappe.utils.format_datetime(frappe.utils.now_datetime(), "dd MMM yyyy"), body)

	def test_unknown_code_is_404_without_data(self):
		issue(make_certificate("Rahul Kumar"), CERT_FORMAT)
		response = self.render("ZZZZZZZZZZ")
		body = response.get_data(as_text=True)
		self.assertEqual(response.status_code, 404)
		self.assertIn("not found", body.lower())
		self.assertNotIn(COLLEGE, body)

	def test_page_is_throttled_with_429_after_30_requests(self):
		for _ in range(30):
			self.assertEqual(self.render("ZZZZZZZZZZ").status_code, 404)
		self.assertEqual(self.render("ZZZZZZZZZZ").status_code, 429)

	def test_public_lookup_masks_name(self):
		record = issue(make_certificate("Rahul Kumar"), CERT_FORMAT)
		self.assertEqual(verification.public_lookup(record.code).holder_name, "R**** K****")
		self.assertEqual(verify(record.code).holder_name, "Rahul Kumar")

	def test_guest_can_call_api(self):
		record = issue(make_certificate(), CERT_FORMAT)
		frappe.db.commit()  # noqa: nothing
		frappe.set_user("Guest")
		self.assertEqual(frappe.call(verification.verify_public, code=record.code).status, "Valid")


class TestRateLimit(VerificationTestCase):
	def setUp(self):
		frappe.cache.delete_keys("rl:*")

	def test_31st_request_per_minute_from_one_ip_is_throttled(self):
		request_as("10.1.1.1")
		for _ in range(30):
			verification.public_lookup("NOSUCHCODE")
		with self.assertRaises(frappe.RateLimitExceededError):
			verification.public_lookup("NOSUCHCODE")

	def test_other_ip_is_not_affected(self):
		request_as("10.1.1.2")
		for _ in range(31):
			try:
				verification.public_lookup("X")
			except frappe.RateLimitExceededError:
				pass
		request_as("10.1.1.3")
		self.assertIsNone(verification.public_lookup("X"))

	def test_rate_limit_error_is_http_429(self):
		self.assertEqual(frappe.RateLimitExceededError.http_status_code, 429)
