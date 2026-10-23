"""P1-T20 tests (M05-04): certificate request -> approve -> issue -> verify, the transfer certificate's dues gate, numbering, ownership."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from campus.campus_finance import api as finance
from campus.campus_platform.approvals import approve, reject
from campus.campus_platform.verification import verify
from campus.student_services import certificate_fee, lifecycle, portal
from campus.student_services.report.certificates_issued import certificates_issued
from campus.student_services.report.tc_register import tc_register
from campus.tests.approval_fixtures import level
from campus.tests.factories import make_user
from campus.tests.finance_factories import make_enrolled_students, make_finance_company, make_year_and_program
from campus.tests.test_results import make_login
from campus.tests.utils import CampusTestCase

COLLEGE, TRUST = "Certificate Test College", "Certificate Test Trust"
YEAR, PROGRAM = "Certificate Test 2026", "Certificate Test BE"
POLICY = "CRT Test Policy"
APPROVER = "crt-approver@example.com"
USERS = {"A": "crt-student-a@example.com", "B": "crt-student-b@example.com"}
GUARDIAN = "crt-guardian@example.com"
BONAFIDE, TRANSFER = "Bonafide", "Transfer Certificate"


class CertificateFixture(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.college = make_finance_company(COLLEGE, "CRTC")
		cls.trust = make_finance_company(TRUST, "CRTT")
		make_year_and_program(COLLEGE, PROGRAM, YEAR)
		_group, students = make_enrolled_students(COLLEGE, PROGRAM, YEAR, 3, "CrtStu")
		cls.a, cls.b, cls.c = students
		make_user(APPROVER, [COLLEGE])
		for key, student in (("A", cls.a), ("B", cls.b)):
			make_login(USERS[key], "Student")
			frappe.db.set_value("Student", student, "user", USERS[key])

	def setUp(self):
		frappe.db.savepoint("certificate_test")
		self.addCleanup(frappe.db.rollback, save_point="certificate_test")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete("Approval Level", {"parent": POLICY})
		frappe.db.delete("Approval Policy", {"name": POLICY})
		frappe.get_doc(
			{
				"doctype": "Approval Policy", "policy_name": POLICY, "document_type": "Certificate Request",
				"condition": "doc.needs_approval", "levels": [level("User", APPROVER, title="Principal")],
			}
		).insert()  # fmt: skip

	def request(self, student, certificate_type=BONAFIDE, **values):
		return frappe.get_doc(
			{"doctype": "Certificate Request", "student": student, "certificate_type": certificate_type, "purpose": "Bank account", **values}
		).insert()

	def approve_request(self, doc):
		"""Send `doc` through the policy and approve it as the approver; returns the reloaded document."""
		from campus.campus_platform.approvals import request_approval

		request = request_approval("Certificate Request", doc.name)
		frappe.set_user(APPROVER)
		approve(request, None)
		frappe.set_user("Administrator")
		doc.reload()
		return doc

	def owe(self, student, company, amount=1000):
		return finance.raise_fee_invoice(student, "Tuition", amount, company, "Certificate test dues")


class TestIssue(CertificateFixture):
	def test_portal_request_approve_issue_verify(self):
		frappe.set_user(USERS["A"])
		row = portal.request_certificate(BONAFIDE, "Bank account")
		self.assertEqual((row["status"], row["pdf_url"], row["certificate_number"]), ("Pending", None, None))
		frappe.set_user("Administrator")
		doc = self.approve_request_pending(row["name"])
		self.assertEqual(doc.docstatus, 1)
		self.assertTrue(doc.certificate_number.startswith("BON/CRTC/"))
		record = verify(doc.verification_code)
		self.assertEqual((record.status, record.company, record.holder_name), ("Valid", COLLEGE, doc.student_name))
		html = frappe.get_print("Certificate Request", doc.name, "Bonafide Certificate")
		self.assertIn("bonafide student", html)
		self.assertIn(doc.certificate_number, html)
		self.assertIn(doc.verification_code, html)  # the QR block links to /verify/<code>
		frappe.set_user(USERS["A"])
		mine = portal.my_certificates()["certificates"]
		self.assertEqual([(c["name"], c["status"]) for c in mine], [(doc.name, "Issued")])
		self.assertIn("Bonafide%20Certificate", mine[0]["pdf_url"])
		self.assertEqual(mine[0]["verification_code"], doc.verification_code)

	def approve_request_pending(self, name):
		request = frappe.db.get_value("Approval Request", {"reference_name": name}, "name")
		frappe.set_user(APPROVER)
		approve(request, None)
		frappe.set_user("Administrator")
		return frappe.get_doc("Certificate Request", name)

	def test_needs_approval_type_cannot_be_issued_without_an_approval_policy(self):
		frappe.db.delete("Approval Level", {"parent": POLICY})
		frappe.db.delete("Approval Policy", {"name": POLICY})
		frappe.set_user(USERS["A"])
		with self.assertRaisesRegex(frappe.ValidationError, "contact the college office"):
			portal.request_certificate(BONAFIDE, "Bank account")

	def test_a_type_that_needs_no_approval_is_issued_at_once(self):
		frappe.db.set_value("Certificate Type", "Conduct", "needs_approval", 0)
		frappe.set_user(USERS["A"])
		row = portal.request_certificate("Conduct", "Scholarship")
		self.assertEqual(row["status"], "Issued")
		self.assertTrue(row["verification_code"])

	def test_a_rejected_request_is_not_issued(self):
		doc = self.request(self.a)
		from campus.campus_platform.approvals import request_approval

		request = request_approval("Certificate Request", doc.name)
		frappe.set_user(APPROVER)
		reject(request, "Not eligible")
		frappe.set_user("Administrator")
		doc.reload()
		self.assertEqual(doc.docstatus, 0)
		self.assertFalse(doc.certificate_number)

	def test_a_non_verifiable_type_gets_no_verifiable_document(self):
		frappe.db.set_value("Certificate Type", BONAFIDE, "verifiable", 0)
		doc = self.approve_request(self.request(self.a))
		self.assertTrue(doc.certificate_number)
		self.assertFalse(doc.verification_code)

	def test_a_second_open_request_of_the_type_is_refused(self):
		self.request(self.a)
		with self.assertRaisesRegex(frappe.ValidationError, "open"):
			self.request(self.a)

	def test_a_disabled_type_is_refused(self):
		frappe.db.set_value("Certificate Type", "Migration", "enabled", 0)
		with self.assertRaisesRegex(frappe.ValidationError, "not available"):
			self.request(self.a, "Migration")

	def test_cancelling_revokes_the_verifiable_document(self):
		doc = self.approve_request(self.request(self.a))
		doc.cancel()
		self.assertEqual(verify(doc.verification_code).status, "Revoked")

	def test_fee_is_invoiced_by_a_worker_not_in_the_request_path(self):
		frappe.db.set_value("Certificate Type", BONAFIDE, "fee_amount", 150)
		frappe.set_user(USERS["A"])
		with patch("frappe.set_user", side_effect=AssertionError("set_user in a request path")):
			row = portal.request_certificate(BONAFIDE, "Bank account")
		doc = self.approve_request_pending(row["name"])
		self.assertEqual(doc.fee_amount, 150)
		certificate_fee.raise_fee(doc.name)
		certificate_fee.raise_fee(doc.name)  # idempotent
		doc.reload()
		invoice = frappe.get_doc("Sales Invoice", doc.fee_invoice)
		self.assertEqual((invoice.docstatus, invoice.grand_total, invoice.items[0].item_code), (1, 150, "Certificate"))
		with self.assertRaisesRegex(frappe.ValidationError, "fee invoice"):
			doc.cancel()


class TestTransferCertificate(CertificateFixture):
	def tc(self, student=None, **values):
		return self.request(student or self.a, TRANSFER, reason_for_leaving="Migrating to another city", **values)

	def test_blocked_while_dues_exist_in_any_company(self):
		for company in (COLLEGE, TRUST):
			invoice = self.owe(self.a, company)
			with self.assertRaisesRegex(frappe.ValidationError, "dues are outstanding"):
				self.tc()
			invoice.cancel()
		self.assertTrue(self.tc().name)  # nothing owed now

	def test_blocked_at_approval_when_dues_arise_after_the_request(self):
		doc = self.tc()
		self.owe(self.a, TRUST)
		from campus.campus_platform.approvals import request_approval

		request = request_approval("Certificate Request", doc.name)
		frappe.set_user(APPROVER)
		with self.assertRaisesRegex(frappe.ValidationError, "dues are outstanding"):
			approve(request, None)

	def test_a_credit_with_one_company_does_not_clear_dues_of_another(self):
		self.owe(self.a, COLLEGE, 5000)
		refund = frappe.get_doc(
			{
				"doctype": "Sales Invoice", "company": TRUST, "student": self.a, "is_return": 1, "posting_date": today(), "due_date": today(),
				"customer": frappe.db.get_value("Student", self.a, "customer"),
				"items": [{"item_code": "Hostel", "qty": -1, "rate": 5000, "income_account": self.trust["income"]}],
			}
		).insert()  # fmt: skip
		refund.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "dues are outstanding"):
			self.tc()

	def test_issue_sets_the_students_leaving_fields_in_one_go(self):
		doc = self.approve_request(self.tc(leaving_date=add_days(today(), 3)))
		student = frappe.get_doc("Student", self.a)
		self.assertEqual(student.leaving_certificate_number, doc.certificate_number)
		self.assertEqual(student.date_of_leaving, getdate(add_days(today(), 3)))
		self.assertEqual(student.reason_for_leaving, "Migrating to another city")
		self.assertEqual(student.oc_academic_status, "Withdrawn")
		log = frappe.get_last_doc("Lifecycle Transition", {"student": self.a}, order_by="creation desc, name desc")
		self.assertEqual(
			(log.from_status, log.to_status, log.effective_date, log.source_doctype, log.source_name, log.reason),
			("Active", "Withdrawn", getdate(add_days(today(), 3)), "Certificate Request", doc.name, "Migrating to another city"),
		)
		self.assertIn("Date of leaving", frappe.get_print("Certificate Request", doc.name, "Transfer Certificate"))

	def test_a_second_tc_is_refused_and_cancelling_the_first_restores_the_student(self):
		doc = self.approve_request(self.tc())
		with self.assertRaisesRegex(frappe.ValidationError, "already has transfer certificate"):
			self.tc()
		doc.cancel()
		student = frappe.get_doc("Student", self.a)
		self.assertFalse(student.leaving_certificate_number)
		self.assertFalse(student.date_of_leaving)
		self.assertEqual(student.oc_academic_status, "Active")
		log = frappe.get_last_doc("Lifecycle Transition", {"student": self.a}, order_by="creation desc, name desc")
		self.assertEqual((log.kind, log.from_status, log.to_status, log.source_name), ("Reversal", "Withdrawn", "Active", doc.name))

	def test_cancelling_a_migrated_tc_restores_active(self):
		doc = self.approve_request(self.tc())
		frappe.db.delete("Lifecycle Transition", {"student": self.a})  # as recorded before L-01
		frappe.db.set_value("Student", self.a, "oc_academic_status", "Discontinued")
		self.assertEqual(lifecycle.migrate_student(self.a), "Withdrawn")
		migrated = frappe.get_last_doc("Lifecycle Transition", {"student": self.a})
		self.assertEqual((migrated.kind, migrated.source_doctype, migrated.source_name), ("Migrated", "Certificate Request", doc.name))
		doc.cancel()
		self.assertEqual(frappe.db.get_value("Student", self.a, "oc_academic_status"), "Active")
		log = frappe.get_last_doc("Lifecycle Transition", {"student": self.a}, order_by="creation desc, name desc")
		self.assertEqual((log.kind, log.from_status, log.to_status, log.reverses), ("Reversal", "Withdrawn", "Active", migrated.name))

	def test_a_tc_to_a_student_who_completed_the_programme_keeps_the_status(self):
		frappe.db.set_value("Student", self.a, "oc_academic_status", "Graduated")
		doc = self.approve_request(self.tc())
		self.assertEqual(frappe.db.get_value("Student", self.a, "oc_academic_status"), "Graduated")
		self.assertFalse(frappe.db.exists("Lifecycle Transition", {"source_name": doc.name}))
		doc.cancel()
		self.assertEqual(frappe.db.get_value("Student", self.a, "oc_academic_status"), "Graduated")

	def test_a_reason_is_required(self):
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			self.request(self.a, TRANSFER)

	def test_a_failed_tc_leaves_the_student_untouched(self):
		self.owe(self.a, COLLEGE)
		with self.assertRaises(frappe.ValidationError):
			self.tc()
		self.assertFalse(frappe.db.get_value("Student", self.a, "leaving_certificate_number"))

	def test_register_lists_the_tc_and_issued_report_the_certificates(self):
		tc = self.approve_request(self.tc())
		bonafide = self.approve_request(self.request(self.b))
		_cols, rows = tc_register.execute({"company": COLLEGE})
		self.assertEqual([r["certificate_number"] for r in rows], [tc.certificate_number])
		_cols, rows = certificates_issued.execute({"company": COLLEGE})
		self.assertEqual({r["certificate_number"] for r in rows}, {tc.certificate_number, bonafide.certificate_number})
		_cols, rows = certificates_issued.execute({"company": COLLEGE, "certificate_type": BONAFIDE})
		self.assertEqual([r["name"] for r in rows], [bonafide.name])
		self.assertEqual(certificates_issued.execute({"company": TRUST})[1], [])


class TestNumbering(CertificateFixture):
	def number(self, student, certificate_type=BONAFIDE):
		return self.approve_request(self.request(student, certificate_type)).certificate_number

	def test_numbers_are_sequential_per_type_company_and_year(self):
		year = getdate(today()).year
		first, second = self.number(self.a), self.number(self.b)
		prefix = f"BON/CRTC/{year}/"
		self.assertTrue(first.startswith(prefix), first)
		self.assertEqual(int(second[len(prefix):]), int(first[len(prefix):]) + 1)
		self.assertEqual(len(first[len(prefix):]), 4)
		other_type = self.number(self.c, "Conduct")  # its own series
		self.assertTrue(other_type.startswith(f"CON/CRTC/{year}/"))
		self.assertEqual(other_type[len(f"CON/CRTC/{year}/"):], "0001")

	def test_each_company_has_its_own_series(self):
		college = self.number(self.a)
		make_user(APPROVER, [TRUST])  # the approver may act for both companies
		student = self.trust_student()
		trust = self.approve_request(self.request(student)).certificate_number
		self.assertTrue(trust.startswith(f"BON/CRTT/{getdate(today()).year}/"))
		self.assertEqual(trust.rsplit("/", 1)[1], "0001")
		self.assertNotEqual(college.split("/")[1], trust.split("/")[1])

	def trust_student(self):
		student = frappe.get_doc(
			{"doctype": "Student", "enabled": 1, "first_name": "Crttrust", "student_email_id": "crttrust@fees.example.com", "oc_company": TRUST}
		).insert()
		return student.name

	def test_prefix_must_carry_company_and_year(self):
		kind = frappe.get_doc("Certificate Type", BONAFIDE)
		kind.number_prefix = "BON/"
		with self.assertRaisesRegex(frappe.ValidationError, "abbr"):
			kind.save()
		kind = frappe.get_doc("Certificate Type", BONAFIDE)
		kind.number_prefix = "BON/{abbr}/{foo}/"
		with self.assertRaisesRegex(frappe.ValidationError, "foo"):
			kind.save()


class TestOwnership(CertificateFixture):
	def test_a_student_cannot_request_or_list_for_another_student(self):
		frappe.set_user(USERS["A"])
		with self.assertRaises(frappe.PermissionError):
			portal.request_certificate(BONAFIDE, "Bank account", student=self.b)
		with self.assertRaises(frappe.PermissionError):
			portal.my_certificates(self.b)
		self.assertFalse(frappe.db.exists("Certificate Request", {"student": self.b}))

	def test_a_student_reads_only_their_own_requests(self):
		frappe.set_user(USERS["B"])
		portal.request_certificate(BONAFIDE, "Bank account")
		frappe.set_user(USERS["A"])
		own = portal.request_certificate(BONAFIDE, "Passport")["name"]
		other = frappe.db.get_value("Certificate Request", {"student": self.b}, "name")
		self.assertEqual(frappe.get_list("Certificate Request", pluck="name"), [own])
		self.assertTrue(frappe.has_permission("Certificate Request", "read", own))
		self.assertFalse(frappe.has_permission("Certificate Request", "read", other))
		self.assertEqual([c["name"] for c in portal.my_certificates()["certificates"]], [own])

	def test_a_student_cannot_create_or_edit_a_request_on_the_desk(self):
		frappe.set_user(USERS["A"])
		self.assertFalse(frappe.has_permission("Certificate Request", "create"))
		self.assertFalse(frappe.has_permission("Certificate Request", "write"))

	def test_a_guardian_acts_for_a_linked_student_only(self):
		from campus.tests.broadcast_fixtures import make_guardian

		make_login(GUARDIAN, "Guardian")
		make_guardian("Crtguardian", [self.a], user=GUARDIAN)
		frappe.set_user(GUARDIAN)
		self.assertEqual(portal.request_certificate(BONAFIDE, "School", student=self.a)["status"], "Pending")
		with self.assertRaises(frappe.PermissionError):
			portal.request_certificate(BONAFIDE, "School", student=self.b)

	def test_the_request_path_never_swaps_the_session_user(self):
		frappe.set_user(USERS["A"])
		session = (frappe.session.user, frappe.session.sid)
		with patch("frappe.set_user", side_effect=AssertionError("set_user in a request path")):
			portal.request_certificate(BONAFIDE, "Bank account")
		self.assertEqual((frappe.session.user, frappe.session.sid), session)

	def test_guests_are_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			portal.request_certificate(BONAFIDE, "Bank account")
		with self.assertRaises(frappe.PermissionError):
			portal.my_certificates()
