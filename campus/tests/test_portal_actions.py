"""P1-T26 (thin-slice S3 portal): certificate requests, grievances, leave and fee payment from /campus-portal.

Each action is POST-only, resolves the student from the session user (a student: themself; a guardian: a ward) and
refuses any other student. Uploads are private. Page contexts are checked like test_student_portal does."""

import base64
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from campus.campus_platform.api import find_policy
from campus.student_services import portal
from campus.tests.broadcast_fixtures import make_guardian
from campus.tests.test_results import make_login
from campus.tests import demo
from campus.tests.approval_fixtures import level
from campus.tests.test_grievances import COLLEGE, EVALUATION, GUARDIAN, STUDENT_A, STUDENT_B, GrievanceFixture
from campus.tests.test_student_portal import make_invoice
from campus.www.campus_portal import (
	certificates as certificates_page,
	fees as fees_page,
	grievances as grievances_page,
	leave as leave_page,
)

BONAFIDE = "Bonafide"
POLICY = "Portal Action Certificate Policy"
BOTH = "pa-both-guardian@example.com"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class PortalActionFixture(GrievanceFixture):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Approval Level", {"parent": POLICY})
		frappe.db.delete("Approval Policy", {"name": POLICY})
		frappe.get_doc(
			{
				"doctype": "Approval Policy", "policy_name": POLICY, "document_type": "Certificate Request",
				"condition": "doc.needs_approval", "levels": [level("Position", "PRINCIPAL", title="Principal", scope_field="company")],
			}
		).insert()  # fmt: skip
		self.addCleanup(frappe.form_dict.clear)

	def page(self, page, user, **form):
		frappe.set_user(user)
		frappe.form_dict.clear()
		frappe.form_dict.update(form)
		context = frappe._dict()
		page.get_context(context)
		return context

	def assert_post_only(self, *methods):
		for method in methods:
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[method], ["POST"], method.__name__)

	def upload(self, name="note.png", content=PNG):
		"""Make the current request carry a file."""
		stream = SimpleNamespace(read=lambda size=-1: content[:size] if size >= 0 else content)
		patcher = patch.object(portal, "posted_file", return_value=SimpleNamespace(filename=name, stream=stream))
		patcher.start()
		self.addCleanup(patcher.stop)


class TestCertificatesPage(PortalActionFixture):
	def test_a_student_requests_and_lists_their_own_certificate(self):
		frappe.set_user(STUDENT_A)
		row = portal.request_certificate(BONAFIDE, "Bank account")
		self.assertEqual((row["certificate_type"], row["status"]), (BONAFIDE, "Pending"))
		context = self.page(certificates_page, STUDENT_A)
		self.assertEqual([c["name"] for c in context.certificates], [row["name"]])
		self.assertIn(BONAFIDE, [t.name for t in context.types])
		self.assertEqual(self.page(certificates_page, STUDENT_B).certificates, [])

	def test_a_guardian_acts_for_their_ward_only(self):
		frappe.set_user(GUARDIAN)
		row = portal.request_certificate(BONAFIDE, "Passport")
		self.assertEqual(frappe.db.get_value("Certificate Request", row["name"], "student"), self.a)
		self.assertEqual(len(self.page(certificates_page, GUARDIAN).certificates), 1)
		with self.assertRaises(frappe.PermissionError):
			portal.request_certificate(BONAFIDE, "Passport", student=self.b)
		with self.assertRaises(frappe.PermissionError):
			self.page(certificates_page, GUARDIAN, student=self.b)

	def test_another_student_is_refused_and_nothing_is_created(self):
		frappe.set_user(STUDENT_A)
		with self.assertRaises(frappe.PermissionError):
			portal.request_certificate(BONAFIDE, "For my friend", student=self.b)
		with self.assertRaises(frappe.PermissionError):
			portal.my_certificates(student=self.b)
		with self.assertRaises(frappe.PermissionError):
			self.page(certificates_page, STUDENT_A, student=self.b)
		self.assertFalse(frappe.db.exists("Certificate Request", {"student": self.b}))

	def test_request_is_post_only(self):
		self.assert_post_only(portal.request_certificate)

	def test_no_approval_route_gives_a_portal_friendly_message_and_creates_nothing(self):
		frappe.db.delete("Approval Level", {"parent": POLICY})
		frappe.db.delete("Approval Policy", {"name": POLICY})
		frappe.set_user(STUDENT_A)
		with self.assertRaises(frappe.ValidationError) as caught:
			portal.request_certificate(BONAFIDE, "Bank account")
		message = str(caught.exception)
		self.assertIn("contact the college office", message)
		self.assertNotIn("Request Approval", message)
		self.assertFalse(frappe.db.exists("Certificate Request", {"student": self.a}))

	def test_a_transfer_certificate_type_must_need_approval(self):
		kind = frappe.get_doc("Certificate Type", "Transfer Certificate")
		kind.needs_approval = 0
		with self.assertRaisesRegex(frappe.ValidationError, "must need approval"):
			kind.save()

	def test_the_demo_policy_is_seeded_once_enabled_and_company_limited_even_in_import_mode(self):
		frappe.db.delete("Approval Level", {"parent": demo.CERTIFICATE_POLICY})
		frappe.db.delete("Approval Policy", {"name": demo.CERTIFICATE_POLICY})
		was_importing, frappe.flags.in_import = frappe.flags.in_import, True  # as make_demo runs
		self.addCleanup(setattr, frappe.flags, "in_import", was_importing)
		demo.make_certificate_policy()
		demo.make_certificate_policy()
		self.assertEqual(frappe.flags.in_import, True)  # restored
		names = frappe.get_all("Approval Policy", {"policy_name": demo.CERTIFICATE_POLICY, "document_type": "Certificate Request"})
		self.assertEqual(len(names), 1)
		policy = frappe.get_doc("Approval Policy", names[0].name)
		self.assertEqual((policy.enabled, policy.levels[0].limit_to_company), (1, 1))
		frappe.db.delete("Approval Level", {"parent": POLICY})
		frappe.db.delete("Approval Policy", {"name": POLICY})
		request = frappe.new_doc("Certificate Request")
		request.update({"student": self.a, "certificate_type": BONAFIDE, "needs_approval": 1, "company": COLLEGE})
		self.assertEqual(find_policy(request).name, policy.name)


class TestGrievancesPage(PortalActionFixture):
	def test_a_student_raises_and_sees_only_their_own_grievances(self):
		frappe.set_user(STUDENT_A)
		row = portal.raise_grievance(EVALUATION, "Marks missing.")
		self.assertEqual([g["name"] for g in self.page(grievances_page, STUDENT_A).grievances], [row["name"]])
		self.assertIn(EVALUATION, [c.name for c in self.page(grievances_page, STUDENT_A).categories])
		self.assertEqual(self.page(grievances_page, STUDENT_B).grievances, [])

	def test_a_guardian_raises_for_their_ward_only(self):
		frappe.set_user(GUARDIAN)
		row = portal.raise_grievance(EVALUATION, "Marks missing.")
		self.assertEqual(frappe.db.get_value("Student Grievance", row["name"], "student"), self.a)
		with self.assertRaises(frappe.PermissionError):
			portal.raise_grievance(EVALUATION, "Not my ward.", student=self.b)
		with self.assertRaises(frappe.PermissionError):
			self.page(grievances_page, GUARDIAN, student=self.b)

	def test_another_student_is_refused(self):
		frappe.set_user(STUDENT_B)
		with self.assertRaises(frappe.PermissionError):
			portal.raise_grievance(EVALUATION, "As A.", student=self.a)
		with self.assertRaises(frappe.PermissionError):
			portal.my_grievances(student=self.a)

	def test_raise_is_post_only(self):
		self.assert_post_only(portal.raise_grievance)

	def test_an_uploaded_attachment_is_private_and_not_listed(self):
		frappe.set_user(STUDENT_A)
		self.upload()
		row = portal.raise_grievance(EVALUATION, "See the attached note.")
		file = frappe.db.get_value(
			"File", {"attached_to_doctype": "Student Grievance", "attached_to_name": row["name"]}, ["is_private", "file_url", "attached_to_field"], as_dict=True
		)
		self.assertEqual(file.is_private, 1)
		self.assertTrue(file.file_url.startswith("/private/files/"))
		self.assertEqual(frappe.db.get_value("Student Grievance", row["name"], "attachment"), file.file_url)
		self.assertNotIn("attachment", row)
		self.assertFalse(any("attachment" in g for g in portal.my_grievances()["grievances"]))

	def test_a_bad_upload_is_refused_before_the_grievance_is_created(self):
		frappe.set_user(STUDENT_A)
		self.upload("run.exe")
		with self.assertRaises(frappe.ValidationError):
			portal.raise_grievance(EVALUATION, "With an exe.")
		self.upload("big.pdf", b"x" * (portal.UPLOAD_MAX_BYTES + 1))
		with self.assertRaises(frappe.ValidationError):
			portal.raise_grievance(EVALUATION, "With a big file.")
		self.assertFalse(frappe.db.exists("Student Grievance", {"student": self.a}))


class TestLeavePage(PortalActionFixture):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Holiday List", "PA Holidays")
		frappe.get_doc(
			{"doctype": "Holiday List", "holiday_list_name": "PA Holidays", "from_date": add_days(today(), -30), "to_date": add_days(today(), 300)}
		).insert()
		frappe.db.set_value("Company", COLLEGE, "default_holiday_list", "PA Holidays")
		frappe.db.set_default("company", COLLEGE)

	def apply(self, **values):
		return portal.apply_leave(**{"from_date": add_days(today(), 3), "to_date": add_days(today(), 4), "leave_kind": "Medical", "reason": "Fever", **values})

	def test_a_student_applies_for_leave_as_a_draft_with_its_kind(self):
		frappe.set_user(STUDENT_A)
		row = self.apply()
		leave = frappe.get_doc("Student Leave Application", row["name"])
		self.assertEqual((leave.student, leave.oc_leave_kind, leave.docstatus), (self.a, "Medical", 0))
		self.assertEqual(row["status"], "Requested")
		self.assertEqual([x["name"] for x in self.page(leave_page, STUDENT_A).leaves], [row["name"]])
		self.assertEqual(self.page(leave_page, STUDENT_B).leaves, [])

	def test_a_guardian_applies_for_their_ward_only(self):
		frappe.set_user(GUARDIAN)
		row = self.apply()
		self.assertEqual(frappe.db.get_value("Student Leave Application", row["name"], "student"), self.a)
		with self.assertRaises(frappe.PermissionError):
			self.apply(student=self.b)
		with self.assertRaises(frappe.PermissionError):
			self.page(leave_page, GUARDIAN, student=self.b)

	def test_another_student_is_refused_and_nothing_is_created(self):
		frappe.set_user(STUDENT_A)
		with self.assertRaises(frappe.PermissionError):
			self.apply(student=self.b)
		with self.assertRaises(frappe.PermissionError):
			portal.my_leaves(student=self.b)
		self.assertFalse(frappe.db.exists("Student Leave Application", {"student": self.b}))

	def test_apply_is_post_only(self):
		self.assert_post_only(portal.apply_leave)

	def test_the_certificate_is_kept_private(self):
		frappe.set_user(STUDENT_A)
		self.upload()
		row = self.apply()
		file = frappe.db.get_value(
			"File", {"attached_to_doctype": "Student Leave Application", "attached_to_name": row["name"]}, ["is_private", "file_url"], as_dict=True
		)
		self.assertEqual(file.is_private, 1)
		self.assertEqual(frappe.db.get_value("Student Leave Application", row["name"], "oc_certificate"), file.file_url)


class TestFeesAndOnboarding(PortalActionFixture):
	def setUp(self):
		super().setUp()
		for name in ("PA-INV-A", "PA-INV-B"):
			frappe.db.delete("Sales Invoice", name)
		student_a, student_b = (frappe.get_doc("Student", s) for s in (self.a, self.b))
		make_invoice(student_a, COLLEGE, 1000, 400, "PA-INV-A")
		make_invoice(student_b, COLLEGE, 500, 500, "PA-INV-B")

	def test_the_button_shows_only_when_the_company_can_take_payment(self):
		with patch.object(portal, "can_pay_online", return_value=False):
			invoices = self.page(fees_page, STUDENT_A).fees.invoices
		self.assertEqual([(i.name, i.can_pay) for i in invoices], [("PA-INV-A", False)])
		with patch.object(portal, "can_pay_online", return_value=True):
			invoices = self.page(fees_page, STUDENT_A).fees.invoices
		self.assertEqual([(i.name, i.can_pay) for i in invoices], [("PA-INV-A", True)])

	def test_no_gateway_set_up_means_no_button(self):
		self.assertFalse(frappe.db.exists("Payment Gateway Account", {"company": COLLEGE}))
		self.assertFalse(self.page(fees_page, STUDENT_A).fees.invoices[0].can_pay)

	def test_pay_invoice_is_own_or_ward_only_and_post_only(self):
		self.assert_post_only(portal.pay_invoice)
		for user, invoice, student in ((STUDENT_A, "PA-INV-B", None), (STUDENT_A, "PA-INV-A", self.b), (GUARDIAN, "PA-INV-B", None)):
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				portal.pay_invoice(invoice, student)
		with patch("campus.campus_finance.gateways.new_request") as new, patch("campus.campus_finance.gateways.gateway_account"), patch(
			"campus.campus_finance.gateways.open_request", return_value=SimpleNamespace(payment_url="https://pay.example/x")
		):
			for user in (STUDENT_A, GUARDIAN):
				frappe.set_user(user)
				self.assertEqual(portal.pay_invoice("PA-INV-A"), {"url": "https://pay.example/x"})
			new.assert_not_called()

	def test_a_switched_ward_cannot_pay_the_other_wards_invoice(self):
		make_login(BOTH, "Guardian")
		make_guardian("Paboth", [self.a, self.b], user=BOTH)
		frappe.set_user(BOTH)
		with patch("campus.campus_finance.gateways.gateway_account"), patch(
			"campus.campus_finance.gateways.open_request", return_value=SimpleNamespace(payment_url="https://pay.example/x")
		):
			self.assertEqual(portal.pay_invoice("PA-INV-B", self.b)["url"], "https://pay.example/x")
			with self.assertRaises(frappe.PermissionError):
				portal.pay_invoice("PA-INV-B", self.a)  # B's invoice while acting for A

	def test_onboarding_is_own_or_ward_only(self):
		frappe.set_user(STUDENT_A)
		self.assertEqual(portal.my_onboarding()["student"] if portal.my_onboarding() else self.a, self.a)
		with self.assertRaises(frappe.PermissionError):
			portal.my_onboarding(self.b)
		frappe.set_user(GUARDIAN)
		with self.assertRaises(frappe.PermissionError):
			portal.my_onboarding(self.b)
