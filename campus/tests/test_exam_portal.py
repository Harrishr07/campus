"""P2-T25 (M06, M16-04) student exam pages of /campus-portal: exam registration fee payment, withdrawal, results of
released sessions only, revaluation application and status with the fee paid through the gateway.

Every portal call resolves the student from the session user (the student themself; a guardian their ward, read
only) and refuses another student. Release dates are enforced server-side: results and grade sheets after
publication (Published and publish_at passed, the ratified version only), revaluation from the release within the
Exam Rule Set's window, withdrawal only while the session is unpublished.

Fixture worlds: campus.tests.test_revaluation.RevaluationFixture (s22 R2022: photocopy before revaluation, a
teacher's justification; s26 R2026: neither) and campus.tests.test_student_records.StudentRecordsFixture
(registrations, an exam schedule, the HOD -> Principal withdrawal policy). The gateway is mocked as in
campus.tests.test_gateways: the Payment Request URL comes from a patched controller, the webhook body is signed here.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.payment_request.payment_request import PaymentRequest
from frappe.utils import add_days, flt, getdate, now_datetime, today

from campus.campus_finance import api as finance
from campus.campus_finance import gateways
from campus.campus_finance.fee_heads import EXAM
from campus.examinations import revaluation
from campus.student_services import exam_portal, portal
from campus.tests.test_gateways import captured, make_gateway_account, signed
from campus.tests.test_results import COE_USER, GUARDIAN_USER, STUDENT_22_USER, STUDENT_26_USER
from campus.tests.test_revaluation import FEES, WINDOW_DAYS, RevaluationFixture
from campus.tests.test_student_records import StudentRecordsFixture
from campus.www.campus_portal import exams as exams_page, revaluation as revaluation_page

URL = "https://pay.example.test/checkout/"
SECRET = "exam-portal-secret"


def as_user(user, method, *args, **kwargs):
	frappe.set_user(user)
	try:
		return method(*args, **kwargs)
	finally:
		frappe.set_user("Administrator")


def page_context(page, user, **form):
	frappe.set_user(user)
	frappe.form_dict.clear()
	frappe.form_dict.update(form)
	try:
		context = frappe._dict()
		page.get_context(context)
		return context
	finally:
		frappe.form_dict.clear()
		frappe.set_user("Administrator")


def portal_body(path, context):
	"""The page's portal_body block rendered alone (the full page needs a web request's boot)."""
	template = frappe.get_jenv().get_template(path)
	return "".join(template.blocks["portal_body"](template.new_context({**frappe.get_jenv().globals, **context, "_": frappe._, "frappe": frappe})))


class GatewayMixin:
	"""A default Razorpay account of the college with a signing secret; the Payment Request URL is patched."""

	def start_gateway(self, company, bank):
		self.gateway_account = make_gateway_account(company, bank)
		for patcher in (
			patch.object(PaymentRequest, "payment_gateway_validation", return_value=True),
			patch.object(PaymentRequest, "get_payment_url", lambda request: URL + request.name),
			patch.dict(frappe.conf, {"campus_gateway_secrets": {self.gateway_account: SECRET}}),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def pay_online(self, invoice, user):
		"""The portal's Pay-now link, then the gateway's signed capture webhook for the whole amount."""
		url = as_user(user, portal.pay_invoice, invoice)["url"]
		request = url.removeprefix(URL)
		amount = flt(frappe.db.get_value("Payment Request", request, "grand_total"))
		body = captured(request, amount, payment_id=f"pay_{request}")
		headers = {"X-Razorpay-Signature": signed(body, SECRET)}
		frappe.set_user("Guest")
		try:
			with patch.object(frappe, "request", SimpleNamespace(get_data=lambda: body)), patch.object(frappe, "get_request_header", headers.get):
				self.assertEqual(gateways.webhook(self.gateway_account), {"status": "accepted"})
		finally:
			frappe.set_user("Administrator")


# ---- revaluation and results -------------------------------------------------------------------


class RevaluationPortalFixture(GatewayMixin, RevaluationFixture):
	def setUp(self):
		super().setUp()
		self.start_gateway(self.session.company, self.bank)

	def mine(self, user=STUDENT_22_USER, **kwargs):
		return as_user(user, exam_portal.my_revaluations, **kwargs)

	def portal_apply(self, kind, courses, user=STUDENT_22_USER, **kwargs):
		return as_user(user, exam_portal.apply_revaluation, self.session.name, kind, frappe.as_json(courses), **kwargs)

	def application(self, row):
		return frappe.get_doc(revaluation.APPLICATION, row["name"])


class TestRevaluationOptions(RevaluationPortalFixture):
	def test_the_open_window_lists_the_eligible_courses_of_the_released_result(self):
		(option,) = self.mine()["options"]
		self.assertEqual(option["exam_session"], self.session.name)
		self.assertEqual(getdate(option["closes_on"]), getdate(add_days(today(), WINDOW_DAYS - 1)))  # published yesterday
		courses = {c["course"]: c["grade"] for c in option["courses"]}
		self.assertEqual(sorted(courses), ["EXM FA", "EXM TH", "EXM TL"])  # EXM LB is a lab: never revalued
		self.assertEqual(courses["EXM FA"], "U")

	def test_nothing_is_offered_before_the_release_nor_after_the_window(self):
		self.publish(add_days(now_datetime(), 1))
		self.assertEqual(self.mine()["options"], [])
		with self.assertRaisesRegex(frappe.ValidationError, "not released"):
			self.portal_apply(revaluation.PHOTOCOPY, ["EXM FA"])
		self.publish(add_days(now_datetime(), -(WINDOW_DAYS + 1)))
		self.assertEqual(self.mine()["options"], [])
		with self.assertRaisesRegex(frappe.ValidationError, "window"):
			self.portal_apply(revaluation.PHOTOCOPY, ["EXM FA"])

	def test_the_actions_are_post_only(self):
		for method in (exam_portal.apply_revaluation, exam_portal.submit_revaluation, exam_portal.apply_withdrawal):
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[method], ["POST"], method.__name__)


class TestRevaluationEndToEnd(RevaluationPortalFixture):
	def test_photocopy_then_revaluation_with_the_fee_paid_through_the_gateway(self):
		row = self.portal_apply(revaluation.PHOTOCOPY, ["EXM FA"])
		self.assertEqual((row["status"], flt(row["fee_amount"])), ("Fee due", FEES["photocopy_fee"]))
		invoice = row["invoice"]
		self.assertTrue(invoice["can_pay"])
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice["name"], "student"), self.s22.name)
		self.pay_online(invoice["name"], STUDENT_22_USER)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice["name"], "outstanding_amount")), 0)
		(listed,) = self.mine()["applications"]
		self.assertEqual((listed["status"], listed["invoice"]["can_pay"]), ("Photocopy being prepared", False))
		as_user(COE_USER, revaluation.issue_photocopy, row["name"])
		self.assertEqual(self.mine()["applications"][0]["status"], "Photocopy issued")

		draft = self.portal_apply(revaluation.REVALUATION, ["EXM FA"])  # R2022: a teacher justifies first
		self.assertEqual((draft["status"], draft["can_submit"], draft["invoice"]), ("Awaiting justification", False, None))
		with self.assertRaisesRegex(frappe.ValidationError, "justification"):
			as_user(STUDENT_22_USER, exam_portal.submit_revaluation, draft["name"])
		self.justify(self.application(draft), "EXM FA")
		self.assertTrue(next(a for a in self.mine()["applications"] if a["name"] == draft["name"])["can_submit"])
		submitted = as_user(STUDENT_22_USER, exam_portal.submit_revaluation, draft["name"])
		self.assertEqual((submitted["status"], flt(submitted["fee_amount"])), ("Fee due", FEES["revaluation_fee"]))
		self.pay_online(submitted["invoice"]["name"], GUARDIAN_USER)  # a guardian may pay a ward's fee
		self.assertEqual(self.mine()["applications"][0]["status"], "Under revaluation")
		self.outcome(self.application(submitted), "EXM FA", 40)
		listed = self.mine()["applications"][0]
		self.assertEqual((listed["status"], listed["courses"][0]["status"]), ("Completed", "Completed"))
		self.assertNotIn("new_ese", frappe.as_json(listed))  # the marks reach the student through the ratified result

	def test_a_regulation_without_the_photocopy_step_submits_at_once(self):
		row = self.portal_apply(revaluation.REVALUATION, ["EXM FA"], user=STUDENT_26_USER, student=self.s26.name)
		self.assertEqual((row["status"], self.application(row).docstatus), ("Fee due", 1))


class TestRevaluationOwnership(RevaluationPortalFixture):
	def test_a_guardian_reads_the_wards_applications_but_only_the_student_applies(self):
		row = self.portal_apply(revaluation.PHOTOCOPY, ["EXM FA"])
		seen = self.mine(GUARDIAN_USER)
		self.assertEqual(([a["name"] for a in seen["applications"]], seen["can_apply"]), ([row["name"]], False))
		with self.assertRaises(frappe.PermissionError):
			self.portal_apply(revaluation.PHOTOCOPY, ["EXM TH"], user=GUARDIAN_USER)

	def test_another_student_is_refused_everywhere(self):
		self.photocopy(["EXM FA"])
		draft = self.portal_apply(revaluation.REVALUATION, ["EXM FA"])
		with self.assertRaises(frappe.PermissionError):
			self.mine(STUDENT_26_USER, student=self.s22.name)
		with self.assertRaises(frappe.PermissionError):
			self.portal_apply(revaluation.PHOTOCOPY, ["EXM FA"], user=STUDENT_26_USER, student=self.s22.name)
		with self.assertRaises(frappe.PermissionError):
			as_user(STUDENT_26_USER, exam_portal.submit_revaluation, draft["name"])
		self.assertEqual([a["name"] for a in self.mine(STUDENT_26_USER)["applications"]], [])
		with self.assertRaises(frappe.PermissionError):
			as_user("Guest", exam_portal.my_revaluations)


class TestReleasedResults(RevaluationPortalFixture):
	def grade(self, user=STUDENT_22_USER):
		(result,) = as_user(user, portal.get_results)["results"]
		return next(c["grade"] for c in result["courses"] if c["course"] == "EXM FA")

	def test_only_the_ratified_version_of_a_released_session_is_shown(self):
		self.assertEqual(self.grade(), "U")
		reval = self.revaluation_paid(["EXM FA"])
		self.outcome(reval, "EXM FA", 40)  # a pending version: U -> A
		self.assertEqual((self.grade(), self.grade(GUARDIAN_USER)), ("U", "U"))
		self.ratify()
		self.assertEqual(self.grade(), "A")

	def test_an_embargoed_session_shows_nothing(self):
		self.publish(add_days(now_datetime(), 1))
		self.assertEqual(as_user(STUDENT_22_USER, portal.get_results)["results"], [])

	def test_the_reader_is_the_released_sessions_helper(self):
		with patch("campus.student_services.portal.released_sessions", return_value=[]) as reader:
			self.assertEqual(as_user(STUDENT_22_USER, portal.get_results)["results"], [])
		reader.assert_called_with(self.session.company)


class TestRevaluationPage(RevaluationPortalFixture):
	def test_the_page_shows_options_and_applications_and_escapes_them(self):
		row = self.portal_apply(revaluation.PHOTOCOPY, ["EXM FA"])
		context = page_context(revaluation_page, STUDENT_22_USER)
		self.assertEqual((context.active, context.revaluations["applications"][0]["name"]), ("revaluation", row["name"]))
		context.revaluations["applications"][0]["exam_session"] = "<script>alert(1)</script>"
		html = portal_body("campus/www/campus_portal/revaluation.html", context)
		self.assertNotIn("<script>alert(1)</script>", html)
		self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
		self.assertIn(row["name"], html)


# ---- exams: registration fee, hall ticket row, withdrawal -------------------------------------------


class ExamPortalFixture(GatewayMixin, StudentRecordsFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from campus.tests.finance_factories import ensure_fiscal_years, ensure_selling_setup, make_account
		from campus.tests.test_exam_registration import with_customer

		ensure_fiscal_years()
		ensure_selling_setup()
		company = cls.session.company
		cls.bank = make_account(company, "EXTC", "Portal Bank", "Bank Accounts", account_type="Bank", root_type="Asset")
		for student in (cls.s22, cls.s26):
			with_customer(student.name)

	def setUp(self):
		super().setUp()
		self.start_gateway(self.session.company, self.bank)

	def exams(self, user=STUDENT_22_USER, **kwargs):
		return as_user(user, exam_portal.my_exams, **kwargs)

	def portal_withdraw(self, courses, user=STUDENT_22_USER, **kwargs):
		return as_user(user, exam_portal.apply_withdrawal, self.session.name, frappe.as_json(courses), "Hospitalised", **kwargs)


class TestRegistrationFee(ExamPortalFixture):
	def test_the_registration_shows_its_exam_fee_invoice_with_a_pay_link(self):
		registration = frappe.db.get_value("Exam Registration", {"student": self.s22.name, "exam_session": self.session.name})
		invoice = finance.raise_fee_invoice(self.s22.name, EXAM, 400, self.session.company, "Exam fee")
		frappe.db.set_value("Exam Registration", registration, {"confirmed": 1, "fee_total": 400, "fee_invoice": invoice.name})
		(row,) = self.exams()["registrations"]
		self.assertEqual((row["name"], row["invoice"]["name"], flt(row["invoice"]["outstanding_amount"])), (registration, invoice.name, 400))
		self.assertTrue(row["invoice"]["can_pay"])
		self.assertIn("hall_ticket", row)
		self.pay_online(invoice.name, STUDENT_22_USER)
		self.assertFalse(self.exams()["registrations"][0]["invoice"]["can_pay"])

	def test_the_exams_page_shows_the_session_users_student_only(self):
		context = page_context(exams_page, STUDENT_22_USER)
		self.assertEqual((context.active, context.exams["student"]), ("exams", self.s22.name))
		self.assertEqual({r["name"] for r in context.exams["registrations"]}, {frappe.db.get_value("Exam Registration", {"student": self.s22.name})})
		with self.assertRaises(frappe.PermissionError):
			page_context(exams_page, STUDENT_26_USER, student=self.s22.name)


class TestWithdrawalPortal(ExamPortalFixture):
	def test_the_student_applies_and_the_application_waits_for_the_hod(self):
		(option,) = self.exams()["withdrawable"]
		self.assertEqual(option["exam_session"], self.session.name)
		self.assertEqual(sorted(option["courses"]), ["EXM FA", "EXM LB", "EXM TH", "EXM TL"])
		row = self.portal_withdraw(["EXM LB"])
		self.assertEqual((row["status"], row["courses"]), ("Pending", ["EXM LB"]))
		doc = frappe.get_doc("Exam Withdrawal Application", row["name"])
		self.assertEqual((doc.student, doc.docstatus, doc.owner), (self.s22.name, 0, STUDENT_22_USER))
		listed = self.exams()
		self.assertEqual([w["name"] for w in listed["withdrawals"]], [row["name"]])
		self.assertNotIn("EXM LB", listed["withdrawable"][0]["courses"])  # one live application per course

	def test_the_window_and_publication_are_enforced(self):
		with self.assertRaisesRegex(frappe.ValidationError, "within 10 days"):
			self.portal_withdraw(["EXM TH"])  # its exam was 11 days ago
		frappe.db.set_value("Exam Session", self.session.name, {"status": "Published", "publish_at": add_days(now_datetime(), -1)})
		self.assertEqual(self.exams()["withdrawable"], [])
		with self.assertRaisesRegex(frappe.ValidationError, "published"):
			self.portal_withdraw(["EXM LB"])

	def test_only_the_student_applies_and_never_for_another(self):
		seen = self.exams(GUARDIAN_USER)
		self.assertEqual((seen["student"], seen["can_act"]), (self.s22.name, False))
		with self.assertRaises(frappe.PermissionError):
			self.portal_withdraw(["EXM LB"], user=GUARDIAN_USER)
		with self.assertRaises(frappe.PermissionError):
			self.portal_withdraw(["EXM LB"], user=STUDENT_26_USER, student=self.s22.name)
		self.assertFalse(frappe.db.exists("Exam Withdrawal Application", {"student": self.s22.name}))

	def test_the_page_escapes_what_the_student_wrote(self):
		row = as_user(STUDENT_22_USER, exam_portal.apply_withdrawal, self.session.name, "EXM LB", "Hospitalised")
		context = page_context(exams_page, STUDENT_22_USER)
		self.assertEqual(context.exams["withdrawals"][0]["name"], row["name"])
		context.exams["withdrawals"][0]["reason"] = "<img src=x onerror=alert(1)>"  # as if stored unsanitised
		html = portal_body("campus/www/campus_portal/exams.html", context)
		self.assertNotIn("<img src=x", html)
		self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)

	def test_a_course_outside_the_registration_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "not registered"):
			self.portal_withdraw(["EXM PRE"])
		self.assertEqual(self.exams(STUDENT_26_USER)["withdrawals"], [])
