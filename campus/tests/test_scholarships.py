"""P1-T22 tests (M05-05): scheme amount/eligibility/renewal rules (unit), disbursement accounting through Payment Entry and
Journal Entry in the right company, concessions as approved line discounts, renewal blocking, arrears, reports and metrics."""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import add_days, add_to_date, now_datetime, today

from campus.campus_finance import api as finance
from campus.campus_finance import concessions, invoices, scholarships
from campus.campus_finance.fee_heads import category_for_type
from campus.campus_finance.report.concession_register import concession_register
from campus.campus_finance.report.scholarship_beneficiaries import (
	scholarship_beneficiaries as beneficiaries_report,
)
from campus.campus_finance.setup import SCHOLARSHIP_POLICY, seed_scholarship_policy
from campus.campus_platform.approvals import approve, request_approval
from campus.examinations.arrears import arrear_courses, outstanding_arrears
from campus.iqac.registry import data_point
from campus.tests.approval_fixtures import approval_not_required, drop_policies, level
from campus.tests.factories import make_user
from campus.tests.finance_factories import (
	make_account,
	make_enrolled_students,
	make_finance_company,
	make_year_and_program,
)  # fmt: skip
from campus.tests.utils import CampusTestCase

COLLEGE, TRUST = "Scholarship Test College", "Scholarship Test Trust"
YEAR, PROGRAM = "Scholarship Test 2026", "Scholarship Test BE"
GOVT, INST = "SCH Test Government", "SCH Test Institutional"
APPROVER, ACCOUNTS, PLAIN = "sch-approver@example.com", "sch-accounts@example.com", "sch-plain@example.com"
POLICY = "SCH Test Concession Policy"
PREVIOUS_YEAR = "Scholarship Test 2025"


class TestRules(UnitTestCase):
	def test_scheme_amount_fixed_percent_and_cap(self):
		self.assertEqual(scholarships.scheme_amount("Fixed", 50000, 0, 0, 999), 50000)
		self.assertEqual(scholarships.scheme_amount("Percent of Fee", 0, 25, 0, 80000), 20000)
		self.assertEqual(scholarships.scheme_amount("Percent of Fee", 0, 25, 15000, 80000), 15000)
		self.assertEqual(scholarships.scheme_amount("Fixed", 50000, 0, 30000, 0), 30000)
		self.assertEqual(scholarships.scheme_amount("Percent of Fee", 0, 25, 0, 0), 0)

	def test_eligibility_reasons(self):
		self.assertEqual(scholarships.eligibility_reasons(1, None, "General"), [])
		self.assertEqual(scholarships.eligibility_reasons(1, "SC", "SC"), [])
		self.assertEqual(len(scholarships.eligibility_reasons(0, None, "General")), 1)
		self.assertIn("SC", scholarships.eligibility_reasons(1, "SC", "General")[0])
		self.assertEqual(len(scholarships.eligibility_reasons(0, "SC", "General")), 2)

	def test_renewal_reasons_arrears(self):
		self.assertEqual(scholarships.renewal_reasons(0, 0, 90, 75), [])
		self.assertEqual(scholarships.renewal_reasons(2, 2, 90, 75), [])  # at the limit
		reasons = scholarships.renewal_reasons(3, 2, 90, 75)
		self.assertEqual(len(reasons), 1)
		self.assertIn("3 arrear", reasons[0])

	def test_renewal_reasons_attendance(self):
		self.assertEqual(scholarships.renewal_reasons(0, 0, 75, 75), [])  # at the bar
		self.assertIn("74.5%", scholarships.renewal_reasons(0, 0, 74.5, 75)[0])
		self.assertIn("No attendance record", scholarships.renewal_reasons(0, 0, None, 75)[0])
		self.assertEqual(scholarships.renewal_reasons(0, 0, None, 0), [])  # no bar, nothing to check
		self.assertEqual(scholarships.renewal_reasons(0, 0, 10, 0), [])

	def test_every_failing_rule_is_reported_together(self):
		self.assertEqual(len(scholarships.renewal_reasons(1, 0, 60, 75)), 2)

	def test_allocate_settles_oldest_first_and_keeps_the_remainder(self):
		invoices = [("A", 30000), ("B", 40000)]
		self.assertEqual(scholarships.allocate(50000, invoices), ([("A", 30000), ("B", 20000)], 0))
		self.assertEqual(scholarships.allocate(80000, invoices), ([("A", 30000), ("B", 40000)], 10000))
		self.assertEqual(scholarships.allocate(10000, invoices), ([("A", 10000)], 0))
		self.assertEqual(scholarships.allocate(5000, []), ([], 5000))

	def test_concession_discount_percent_amount_and_never_above_the_fee(self):
		self.assertEqual(concessions.concession_discount(10000, "Percent", 10, 0), 1000)
		self.assertEqual(concessions.concession_discount(10000, "Amount", 0, 2500), 2500)
		self.assertEqual(concessions.concession_discount(10000, "Amount", 0, 25000), 10000)
		self.assertEqual(concessions.concession_discount(0, "Percent", 10, 0), 0)

	def test_an_opening_invoice_is_recognised_in_any_case(self):
		for value, expected in (
			("Yes", True),
			("yes", True),
			(" YES ", True),
			("No", False),
			("", False),
			(None, False),
		):
			self.assertEqual(invoices.is_opening(frappe._dict(is_opening=value)), expected, value)

	def test_outstanding_arrears_latest_outcome_wins(self):
		self.assertEqual(outstanding_arrears([("C1", "Fail"), ("C2", "Pass")]), ["C1"])
		self.assertEqual(outstanding_arrears([("C1", "Fail"), ("C2", "Pass"), ("C1", "Pass")]), [])
		self.assertEqual(outstanding_arrears([("C1", "Pass"), ("C1", "Fail")]), ["C1"])
		self.assertEqual(outstanding_arrears([("C1", "SA"), ("C2", "AB"), ("C3", "Pass")]), ["C1", "C2"])
		self.assertEqual(outstanding_arrears([]), [])


class ScholarshipFixture(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.college = make_finance_company(COLLEGE, "SCHC")
		cls.trust = make_finance_company(TRUST, "SCHT")
		if not frappe.db.exists("Party Type", "Customer"):  # the bare test site lacks ERPNext's party types
			frappe.get_doc(
				{"doctype": "Party Type", "party_type": "Customer", "account_type": "Receivable"}
			).insert()
		cls.expense = make_account(
			COLLEGE, "SCHC", "Scholarship Expense", "Indirect Expenses", root_type="Expense"
		)
		make_year_and_program(COLLEGE, PROGRAM, YEAR)
		_group, students = make_enrolled_students(COLLEGE, PROGRAM, YEAR, 3, "SchStu")
		cls.a, cls.b, cls.c = students
		make_user(APPROVER, [COLLEGE])
		make_user(ACCOUNTS, [COLLEGE])
		make_user(PLAIN, [COLLEGE])
		frappe.get_doc("User", APPROVER).add_roles("Accounts User")
		frappe.get_doc("User", ACCOUNTS).add_roles("Accounts User")

	def setUp(self):
		frappe.db.savepoint("scholarship_test")
		self.addCleanup(frappe.db.rollback, save_point="scholarship_test")
		drop_policies(
			"Scholarship Application"
		)  # these tests sanction by submitting; TestMandatoryApproval covers the list
		mandatory = approval_not_required()
		mandatory.start()
		self.addCleanup(mandatory.stop)
		self.addCleanup(frappe.set_user, "Administrator")
		self.govt = self.make_scheme(GOVT, "Government", self.college["bank"])
		self.inst = self.make_scheme(
			INST,
			"Institutional",
			self.expense,
			renewable=1,
			renewal_min_attendance_pct=75,
			renewal_max_arrears=1,
		)

	def make_scheme(self, name, scheme_type, account, **values):
		if frappe.db.exists("Scholarship Scheme", name):
			frappe.delete_doc("Scholarship Scheme", name, force=True)
		return frappe.get_doc(
			{
				"doctype": "Scholarship Scheme",
				"scheme_name": name,
				"company": COLLEGE,
				"scheme_type": scheme_type,
				"account": account,
				"amount_type": "Fixed",
				"amount": 50000,
				**values,
			}
		).insert()

	def application(self, student, scheme, submit=True, **values):
		doc = frappe.get_doc(
			{
				"doctype": "Scholarship Application",
				"student": student,
				"scheme": scheme.name,
				"academic_year": YEAR,
				**values,
			}
		).insert()
		return doc.submit() if submit else doc

	def owe(self, student, company, amount=80000, head="Tuition"):
		return finance.raise_fee_invoice(student, head, amount, company, "Scholarship test dues")


def opening_invoice(student, amount):
	"""An opening fee balance as the legacy import books it: is_opening, into the Temporary Opening account."""
	invoice = frappe.get_doc(
		{
			"doctype": "Sales Invoice", "company": COLLEGE, "customer": frappe.db.get_value("Student", student, "customer"),
			"student": student, "is_opening": "Yes", "posting_date": today(), "set_posting_time": 1, "due_date": today(),
			"debit_to": frappe.db.get_value("Company", COLLEGE, "default_receivable_account"),
			"items": [{"item_code": category_for_type("Tuition"), "qty": 1, "rate": amount, "income_account": "Temporary Opening - SCHC"}],
		}
	)  # fmt: skip
	invoice.flags.ignore_permissions = True
	return invoice.insert().submit()


class TestChallanNumbers(ScholarshipFixture):
	def test_an_opening_balance_and_a_credit_note_get_no_challan_number(self):
		self.assertTrue(self.owe(self.a, COLLEGE, 1000).oc_challan_no)  # a fee invoice does
		self.assertFalse(opening_invoice(self.a, 10000).oc_challan_no)
		invoice = self.owe(self.b, COLLEGE, 1000)
		self.assertFalse(
			finance.make_credit_note(frappe.get_doc("Sales Invoice", invoice.name), 400).oc_challan_no
		)


class TestDisbursement(ScholarshipFixture):
	def test_a_government_scholarship_of_50000_reduces_the_outstanding_when_disbursed(self):
		invoice = self.owe(self.a, COLLEGE)
		self.assertEqual(finance.has_dues(self.a).total, 80000)
		application = self.application(self.a, self.govt)
		self.assertEqual(
			(application.sanctioned_amount, application.status, application.company),
			(50000, "Sanctioned", COLLEGE),
		)
		self.assertEqual(finance.has_dues(self.a).total, 80000)  # sanctioned is not yet disbursed
		row = scholarships.disburse(application.name, 50000, "UTR123")
		self.assertEqual((row["voucher_type"], row["amount"]), ("Payment Entry", 50000))
		self.assertEqual(finance.has_dues(self.a).total, 30000)
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), 30000)
		payment = frappe.get_doc("Payment Entry", row["voucher"])
		self.assertEqual(
			(payment.docstatus, payment.payment_type, payment.company, payment.paid_to, payment.reference_no),
			(1, "Receive", COLLEGE, self.college["bank"], "UTR123"),
		)
		self.assertEqual(
			[(r.reference_name, r.allocated_amount) for r in payment.references], [(invoice.name, 50000)]
		)
		application.reload()
		self.assertEqual((application.status, application.disbursed_amount), ("Disbursed", 50000))
		self.assertEqual(
			[(d.voucher_type, d.voucher) for d in application.disbursements],
			[("Payment Entry", payment.name)],
		)

	def test_an_institutional_scholarship_waives_the_dues_through_a_journal_entry(self):
		invoice = self.owe(self.a, COLLEGE, 60000)
		application = self.application(self.a, self.inst)
		row = scholarships.disburse(application.name, 20000)
		self.assertEqual(row["voucher_type"], "Journal Entry")
		entry = frappe.get_doc("Journal Entry", row["voucher"])
		debit = next(a for a in entry.accounts if a.debit_in_account_currency)
		credit = next(a for a in entry.accounts if a.credit_in_account_currency)
		self.assertEqual(
			(entry.docstatus, entry.company, debit.account, debit.debit_in_account_currency),
			(1, COLLEGE, self.expense, 20000),
		)
		self.assertEqual(
			(credit.account, credit.party, credit.reference_name),
			(self.college_receivable(), frappe.db.get_value("Student", self.a, "customer"), invoice.name),
		)
		self.assertEqual(finance.has_dues(self.a).total, 40000)

	def college_receivable(self):
		return frappe.db.get_value("Company", COLLEGE, "default_receivable_account")

	def test_the_credit_goes_to_the_schemes_company_only(self):
		college_invoice, trust_invoice = (
			self.owe(self.a, COLLEGE, 30000),
			self.owe(self.a, TRUST, 40000, "Hostel"),
		)
		application = self.application(self.a, self.govt)
		scholarships.disburse(application.name, 50000)
		dues = finance.has_dues(self.a)
		self.assertEqual(dues.by_company, {TRUST: 40000})  # the college is settled, the trust untouched
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", trust_invoice.name, "outstanding_amount"), 40000
		)
		self.assertEqual(frappe.db.get_value("Sales Invoice", college_invoice.name, "outstanding_amount"), 0)
		payment = frappe.get_doc("Payment Entry", application.reload().disbursements[0].voucher)
		self.assertEqual(payment.company, COLLEGE)
		self.assertEqual(
			payment.paid_from, self.college_receivable()
		)  # 20000 beyond the invoices stays on account

	def test_dues_are_settled_oldest_invoice_first(self):
		first, second = self.owe(self.a, COLLEGE, 30000), self.owe(self.a, COLLEGE, 40000)
		frappe.db.set_value("Sales Invoice", first.name, "posting_date", add_days(today(), -5))
		application = self.application(self.a, self.govt)
		scholarships.disburse(application.name, 35000)
		self.assertEqual(frappe.db.get_value("Sales Invoice", first.name, "outstanding_amount"), 0)
		self.assertEqual(frappe.db.get_value("Sales Invoice", second.name, "outstanding_amount"), 35000)

	def test_disbursements_cannot_exceed_the_sanctioned_amount(self):
		self.owe(self.a, COLLEGE)
		application = self.application(self.a, self.govt)
		scholarships.disburse(application.name, 30000)
		with self.assertRaisesRegex(frappe.ValidationError, "20000.0 of the sanctioned"):
			scholarships.disburse(application.name, 20001)
		scholarships.disburse(application.name, 20000)
		self.assertEqual(
			frappe.db.get_value("Scholarship Application", application.name, "status"), "Disbursed"
		)
		with self.assertRaises(frappe.ValidationError):
			scholarships.disburse(application.name, 1)

	def test_a_cancelled_voucher_stops_counting_and_reopens_the_balance(self):
		self.owe(self.a, COLLEGE)
		application = self.application(self.a, self.govt)
		row = scholarships.disburse(application.name, 50000)
		frappe.get_doc("Payment Entry", row["voucher"]).cancel()
		application.reload()
		self.assertEqual((application.disbursed_amount, application.status), (0, "Sanctioned"))
		scholarships.disburse(application.name, 50000)
		self.assertEqual(
			frappe.db.get_value("Scholarship Application", application.name, "disbursed_amount"), 50000
		)

	def test_an_application_with_live_disbursements_cannot_be_cancelled(self):
		self.owe(self.a, COLLEGE)
		application = self.application(self.a, self.govt)
		scholarships.disburse(application.name, 10000)
		with self.assertRaisesRegex(frappe.ValidationError, "disbursement vouchers"):
			application.cancel()

	def test_only_accounts_roles_may_disburse_and_only_sanctioned_applications(self):
		application = self.application(self.a, self.govt)
		draft = self.application(self.b, self.govt, submit=False)
		self.owe(self.a, COLLEGE, 1000)
		for user in ("Guest", PLAIN):
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				scholarships.disburse(application.name, 100)
		frappe.set_user(ACCOUNTS)
		self.assertEqual(scholarships.disburse(application.name, 100)["amount"], 100)
		frappe.set_user("Administrator")
		with self.assertRaisesRegex(frappe.ValidationError, "not sanctioned"):
			scholarships.disburse(draft.name, 100)


class TestApplicationRules(ScholarshipFixture):
	def test_a_listed_sanction_without_an_approval_policy_is_refused(self):
		self.addCleanup(frappe.db.after_rollback.reset)  # the refusal's flag never commits inside a test
		doc = self.application(self.a, self.govt, submit=False)
		with approval_not_required(required=True):
			with self.assertRaisesRegex(
				frappe.ValidationError, "No approval policy is configured for Scholarship Application"
			):
				request_approval("Scholarship Application", doc.name)
			with self.assertRaisesRegex(frappe.ValidationError, "No approval policy is configured"):
				doc.reload().submit()
		self.assertEqual(frappe.db.get_value("Scholarship Application", doc.name, "docstatus"), 0)

	def test_a_listed_sanction_with_an_approval_policy_is_sanctioned_on_approval(self):
		frappe.get_doc(
			{"doctype": "Approval Policy", "policy_name": "SCH Test Sanction Policy", "document_type": "Scholarship Application", "levels": [level("User", APPROVER, title="Principal")]}
		).insert()  # fmt: skip
		doc = self.application(self.a, self.govt, submit=False)
		with approval_not_required(required=True):
			request = request_approval("Scholarship Application", doc.name)
			frappe.set_user(APPROVER)
			try:
				approve(request, None)
			finally:
				frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("Scholarship Application", doc.name, ["docstatus", "status"]),
			(1, "Sanctioned"),
		)

	def test_the_principal_alone_can_open_and_approve_a_sanction(self):
		principal = "sch-principal@example.com"
		make_user(principal, [COLLEGE])
		frappe.get_doc("User", principal).add_roles("Principal")
		frappe.get_doc(
			{"doctype": "Approval Policy", "policy_name": "SCH Principal Policy", "document_type": "Scholarship Application", "levels": [level("User", principal, title="Principal")]}
		).insert()  # fmt: skip
		doc = self.application(self.a, self.govt, submit=False)
		with approval_not_required(required=True):
			request = request_approval("Scholarship Application", doc.name)
			frappe.set_user(principal)
			try:
				self.assertTrue(frappe.has_permission("Scholarship Application", "read", doc.name))
				approve(request, None)
			finally:
				frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("Scholarship Application", doc.name, ["docstatus", "status"]),
			(1, "Sanctioned"),
		)

	def test_an_approver_who_cannot_open_the_document_is_refused_when_the_level_starts(self):
		blind = "sch-blind@example.com"
		make_user(blind, [COLLEGE])
		frappe.get_doc(
			{"doctype": "Approval Policy", "policy_name": "SCH Blind Policy", "document_type": "Scholarship Application", "levels": [level("User", blind, title="Blind")]}
		).insert()  # fmt: skip
		doc = self.application(self.a, self.govt, submit=False)
		with approval_not_required(required=True):
			with self.assertRaisesRegex(frappe.ValidationError, "cannot open Scholarship Application"):
				request_approval("Scholarship Application", doc.name)

	def test_the_sanctioned_amount_defaults_to_the_rule_and_may_only_be_lowered(self):
		doc = self.application(self.a, self.govt, submit=False)
		self.assertEqual(doc.sanctioned_amount, 50000)
		doc.sanctioned_amount = 60000
		with self.assertRaisesRegex(frappe.ValidationError, "cannot exceed 50000"):
			doc.save()
		doc.reload()
		doc.sanctioned_amount = 40000
		self.assertEqual(doc.save().sanctioned_amount, 40000)

	def test_a_percent_of_fee_scheme_takes_the_fee_with_its_cap(self):
		scheme = self.make_scheme(
			"SCH Test Percent",
			"Government",
			self.college["bank"],
			amount_type="Percent of Fee",
			amount=0,
			percent=25,
			max_amount=15000,
		)
		self.assertEqual(
			self.application(self.a, scheme, base_fee=80000, submit=False).sanctioned_amount, 15000
		)
		self.assertEqual(
			self.application(self.b, scheme, base_fee=40000, submit=False).sanctioned_amount, 10000
		)

	def test_one_live_application_per_student_scheme_and_year(self):
		self.application(self.a, self.govt)
		with self.assertRaisesRegex(frappe.ValidationError, "already covers"):
			self.application(self.a, self.govt, submit=False)

	def test_the_scheme_must_belong_to_the_students_company(self):
		other = self.make_scheme("SCH Test Other", "Government", self.college["bank"])
		frappe.db.set_value("Scholarship Scheme", other.name, "company", TRUST)
		with self.assertRaisesRegex(frappe.ValidationError, "not to the student's company"):
			self.application(self.a, other, submit=False)

	def test_a_closed_scheme_or_the_wrong_category_is_not_eligible(self):
		frappe.db.set_value("Scholarship Scheme", self.govt.name, "enabled", 0)
		with self.assertRaisesRegex(frappe.ValidationError, "not open"):
			self.application(self.a, self.govt, submit=False)
		frappe.db.set_value(
			"Scholarship Scheme", self.govt.name, {"enabled": 1, "eligible_student_category": "Reserved"}
		)
		if not frappe.db.exists("Student Category", "Reserved"):
			frappe.get_doc({"doctype": "Student Category", "category": "Reserved"}).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "student category"):
			self.application(self.a, self.govt, submit=False)

	def test_account_kinds_are_checked_on_the_scheme(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Bank or Cash"):
			self.make_scheme("SCH Test Bad Govt", "Government", self.expense)
		with self.assertRaisesRegex(frappe.ValidationError, "Expense account"):
			self.make_scheme("SCH Test Bad Inst", "Institutional", self.college["bank"])
		with self.assertRaisesRegex(frappe.ValidationError, "ledger account of"):
			self.make_scheme("SCH Test Foreign", "Government", self.trust["bank"])


class TestRenewal(ScholarshipFixture):
	def setUp(self):
		super().setUp()
		year = int(today()[:4]) - 1
		if not frappe.db.exists("Academic Year", PREVIOUS_YEAR):
			frappe.get_doc(
				{
					"doctype": "Academic Year",
					"academic_year_name": PREVIOUS_YEAR,
					"year_start_date": f"{year}-01-01",
					"year_end_date": f"{year}-12-31",
				}
			).insert()
		self.first = self.application(self.a, self.inst, academic_year=PREVIOUS_YEAR)
		for target, value in (
			("campus.examinations.api.arrear_courses", []),
			("campus.student_services.api.latest_attendance", ("T1", 90.0)),
		):
			patcher = patch(target, return_value=value)
			patcher.start()
			self.addCleanup(patcher.stop)

	def renewal(self, **values):
		doc = {"application_type": "Renewal", "previous_application": self.first.name, "academic_year": YEAR}
		return frappe.get_doc(
			{
				"doctype": "Scholarship Application",
				"student": self.a,
				"scheme": self.inst.name,
				**doc,
				**values,
			}
		)

	def test_a_renewal_that_meets_the_criteria_is_sanctioned(self):
		doc = self.renewal()
		with patch.object(
			type(doc), "check_duplicate"
		):  # the fixture has one academic year, so the earlier one is the same
			doc.insert()
			self.assertEqual(doc.submit().status, "Sanctioned")

	def test_a_renewal_is_blocked_with_every_reason_when_arrears_and_attendance_fail(self):
		with (
			patch("campus.examinations.api.arrear_courses", return_value=["C1", "C2"]),
			patch("campus.student_services.api.latest_attendance", return_value=("T1", 60.0)),
			patch.object(type(self.renewal()), "check_duplicate"),
		):
			with self.assertRaises(frappe.ValidationError) as caught:
				self.renewal().insert()
		message = str(caught.exception)
		self.assertIn("2 arrear(s) pending; the scheme allows 1", message)
		self.assertIn("Attendance 60.0% is below the required 75.0%", message)

	def test_one_failing_rule_alone_blocks(self):
		with (
			patch("campus.examinations.api.arrear_courses", return_value=["C1", "C2"]),
			patch.object(type(self.renewal()), "check_duplicate"),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "arrear"):
				self.renewal().insert()
		with (
			patch("campus.student_services.api.latest_attendance", return_value=("T1", None)),
			patch.object(type(self.renewal()), "check_duplicate"),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "No attendance record"):
				self.renewal().insert()

	def test_the_criteria_are_checked_again_at_sanction(self):
		with patch.object(type(self.renewal()), "check_duplicate"):
			doc = self.renewal().insert()
			with patch("campus.examinations.api.arrear_courses", return_value=["C1", "C2", "C3"]):
				with self.assertRaisesRegex(frappe.ValidationError, "arrear"):
					doc.submit()

	def test_a_renewal_needs_a_renewable_scheme_and_the_sanctioned_earlier_application(self):
		frappe.db.set_value("Scholarship Scheme", self.inst.name, "renewable", 0)
		with (
			patch.object(type(self.renewal()), "check_duplicate"),
			self.assertRaisesRegex(frappe.ValidationError, "cannot be renewed"),
		):
			self.renewal().insert()
		frappe.db.set_value("Scholarship Scheme", self.inst.name, "renewable", 1)
		with (
			patch.object(type(self.renewal()), "check_duplicate"),
			self.assertRaisesRegex(frappe.ValidationError, "sanctioned application of the same scheme"),
		):
			self.renewal(previous_application=None).insert()

	def test_a_scheme_with_no_attendance_bar_skips_the_attendance_lookup(self):
		frappe.db.set_value("Scholarship Scheme", self.inst.name, "renewal_min_attendance_pct", 0)
		with (
			patch("campus.student_services.api.latest_attendance", side_effect=AssertionError("not needed")),
			patch.object(type(self.renewal()), "check_duplicate"),
		):
			self.renewal().insert()


class TestArrears(CampusTestCase):
	def test_arrears_come_from_published_results_only(self):
		make_finance_company(COLLEGE, "SCHC")
		make_year_and_program(COLLEGE, PROGRAM, YEAR)
		_group, students = make_enrolled_students(COLLEGE, PROGRAM, YEAR, 1, "SchArr")
		student = students[0]
		frappe.db.savepoint("arrears_test")
		self.addCleanup(frappe.db.rollback, save_point="arrears_test")
		term = self.make_term()
		earlier = self.session(term, add_to_date(now_datetime(), days=-30))
		later = self.session(term, add_to_date(now_datetime(), days=-10))
		unpublished = self.session(term, add_to_date(now_datetime(), days=-1), status="Marks Entry")
		self.result(student, earlier, [("C1", "Fail"), ("C2", "Pass"), ("C3", "AB")])
		self.assertEqual(arrear_courses(student), ["C1", "C3"])
		self.result(student, later, [("C1", "Pass")])
		self.assertEqual(arrear_courses(student), ["C3"])  # C1 cleared by a later Pass
		self.result(student, unpublished, [("C2", "Fail")])
		self.assertEqual(arrear_courses(student), ["C3"])  # unpublished results do not count

	def make_term(self):
		name = "SCH Arrear Term"
		if not frappe.db.exists("Academic Term", f"{YEAR} ({name})"):
			frappe.get_doc(
				{
					"doctype": "Academic Term",
					"academic_year": YEAR,
					"term_name": name,
					"term_start_date": f"{today()[:4]}-01-01",
					"term_end_date": f"{today()[:4]}-01-31",
				}
			).insert()
		return f"{YEAR} ({name})"

	def session(self, term, publish_at, status="Published"):
		doc = frappe.new_doc("Exam Session")
		doc.update({"company": COLLEGE, "academic_term": term, "status": status, "publish_at": publish_at})
		doc.name = frappe.generate_hash(length=10)
		doc.db_insert()
		return doc.name

	def result(self, student, session, courses):
		doc = frappe.new_doc("Student Result")
		doc.update({"student": student, "exam_session": session, "company": COLLEGE})
		doc.name = frappe.generate_hash(length=10)
		doc.db_insert()
		for idx, (course, outcome) in enumerate(courses, 1):
			row = frappe.new_doc("Student Result Course")
			row.update(
				{
					"parent": doc.name,
					"parenttype": "Student Result",
					"parentfield": "courses",
					"idx": idx,
					"course": course,
					"result": outcome,
				}
			)
			row.name = frappe.generate_hash(length=10)
			row.db_insert()


class TestConcession(ScholarshipFixture):
	def setUp(self):
		super().setUp()
		frappe.db.set_value("Fee Category", "Tuition", "oc_concession_allowed", 1)
		frappe.db.set_value("Fee Category", "Exam", "oc_concession_allowed", 0)
		frappe.db.delete("Approval Level", {"parent": ["in", [POLICY, "Fee Concession Approval"]]})
		frappe.db.delete("Approval Policy", {"name": ["in", [POLICY, "Fee Concession Approval"]]})
		frappe.get_doc(
			{
				"doctype": "Approval Policy",
				"policy_name": POLICY,
				"document_type": "Fee Concession",
				"levels": [level("User", APPROVER, title="Principal")],
			}
		).insert()

	def concession(self, student=None, **values):
		return frappe.get_doc(
			{
				"doctype": "Fee Concession",
				"student": student or self.a,
				"academic_year": YEAR,
				"fee_category": "Tuition",
				"concession_type": "Percent",
				"percent": 10,
				"reason": "Merit",
				**values,
			}
		).insert()

	def approved(self, student=None, **values):
		doc = self.concession(student, **values)
		request = request_approval("Fee Concession", doc.name)
		frappe.set_user(APPROVER)
		approve(request, None)
		frappe.set_user("Administrator")
		return doc.reload()

	def test_an_approved_concession_becomes_a_discount_line_on_the_fee_invoice(self):
		concession = self.approved()
		self.assertEqual((concession.docstatus, concession.status), (1, "Open"))
		invoice = self.owe(self.a, COLLEGE, 10000)
		self.assertEqual(invoice.grand_total, 9000)
		line = invoice.items[0]
		self.assertEqual(
			(len(invoice.items), line.price_list_rate, line.discount_amount, line.rate),
			(1, 10000, 1000, 9000),
		)
		self.assertEqual(line.oc_fee_concession, concession.name)
		self.assertEqual(finance.has_dues(self.a).total, 9000)
		concession.reload()
		self.assertEqual(
			(concession.status, concession.applied_invoice, concession.discount_amount),
			("Applied", invoice.name, 1000),
		)

	def test_a_concession_discounts_one_invoice_only(self):
		self.approved()
		self.owe(self.a, COLLEGE, 10000)
		self.assertEqual(self.owe(self.a, COLLEGE, 10000).grand_total, 10000)

	def test_it_applies_only_to_its_fee_category(self):
		self.approved()
		self.assertEqual(self.owe(self.a, COLLEGE, 5000, "Library").grand_total, 5000)
		self.assertEqual(frappe.db.get_value("Fee Concession", {"student": self.a}, "status"), "Open")

	def test_only_configured_fee_categories_can_be_conceded(self):
		with self.assertRaisesRegex(frappe.ValidationError, "not configured for concessions"):
			self.concession(fee_category="Exam")

	def test_it_cannot_be_submitted_without_approval(self):
		doc = self.concession()
		with self.assertRaisesRegex(frappe.ValidationError, "needs approval"):
			doc.submit()
		frappe.db.delete("Approval Level", {"parent": POLICY})
		frappe.db.delete("Approval Policy", {"name": POLICY})
		with self.assertRaisesRegex(frappe.ValidationError, "needs approval"):
			self.concession(self.b).submit()  # no policy at all: still not submittable

	def test_a_rejected_concession_never_discounts(self):
		doc = self.concession()
		request = request_approval("Fee Concession", doc.name)
		frappe.set_user(APPROVER)
		from campus.campus_platform.approvals import reject

		reject(request, "No")
		frappe.set_user("Administrator")
		self.assertEqual(self.owe(self.a, COLLEGE, 10000).grand_total, 10000)

	def test_an_amount_concession_is_capped_at_the_fee(self):
		self.approved(concession_type="Amount", amount=30000)
		self.assertEqual(self.owe(self.a, COLLEGE, 10000).grand_total, 0)

	def test_other_students_and_other_years_are_not_discounted(self):
		self.approved()
		self.assertEqual(self.owe(self.b, COLLEGE, 10000).grand_total, 10000)
		frappe.db.set_value(
			"Academic Year",
			YEAR,
			{"year_start_date": add_days(today(), 400), "year_end_date": add_days(today(), 700)},
		)
		self.assertEqual(self.owe(self.a, COLLEGE, 10000).grand_total, 10000)

	def test_an_opening_balance_takes_no_concession(self):
		concession = self.approved()
		opening = opening_invoice(self.a, 10000)
		self.assertEqual(
			(opening.grand_total, opening.items[0].discount_amount, opening.items[0].oc_fee_concession),
			(10000, 0, None),
		)
		self.assertEqual(concession.reload().status, "Open")
		self.assertEqual(
			self.owe(self.a, COLLEGE, 10000).grand_total, 9000
		)  # the next real fee invoice takes it

	def test_cancelling_the_invoice_releases_the_concession(self):
		concession = self.approved()
		invoice = self.owe(self.a, COLLEGE, 10000)
		with self.assertRaisesRegex(frappe.ValidationError, "cancel the invoice first"):
			concession.reload().cancel()
		invoice.cancel()
		concession.reload()
		self.assertEqual(
			(concession.status, concession.applied_invoice, concession.discount_amount), ("Open", None, 0)
		)
		self.assertEqual(self.owe(self.a, COLLEGE, 10000).grand_total, 9000)

	def test_the_register_lists_state_and_invoice(self):
		applied, waiting = self.approved(), self.approved(self.b, percent=20)
		draft = self.concession(self.c)
		invoice = self.owe(self.a, COLLEGE, 10000)
		rows = {r["name"]: r for r in concession_register.execute({"company": COLLEGE})[1]}
		self.assertEqual(
			(
				rows[applied.name]["state"],
				rows[applied.name]["applied_invoice"],
				rows[applied.name]["discount_amount"],
			),
			("Applied", invoice.name, 1000),
		)
		self.assertEqual((rows[waiting.name]["state"], rows[waiting.name]["concession"]), ("Open", "20.0%"))
		self.assertEqual(rows[draft.name]["state"], "Awaiting approval")
		self.assertEqual(concession_register.execute({"company": "Nowhere"})[1], [])


class TestBeneficiaries(ScholarshipFixture):
	def test_report_and_metrics_split_government_5_1_1_from_institutional_5_1_2(self):
		self.owe(self.a, COLLEGE)
		gov_a, gov_b, inst_c = (
			self.application(self.a, self.govt),
			self.application(self.b, self.govt),
			self.application(self.c, self.inst),
		)
		self.application(self.b, self.inst, submit=False)  # a draft is not a beneficiary
		scholarships.disburse(gov_a.name, 50000)
		columns, rows, _msg, _chart, summary = beneficiaries_report.execute(
			{"company": COLLEGE, "academic_year": YEAR}
		)
		clauses = {(r["name"], r["aqar_clause"]) for r in rows}
		self.assertEqual(clauses, {(gov_a.name, "5.1.1"), (gov_b.name, "5.1.1"), (inst_c.name, "5.1.2")})
		self.assertEqual(next(r for r in rows if r["name"] == gov_a.name)["disbursed_amount"], 50000)
		self.assertEqual(
			{s["label"]: s["value"] for s in summary},
			{"5.1.1 Government (students)": 2, "5.1.2 Institutional (students)": 1},
		)
		only = beneficiaries_report.execute(
			{"company": COLLEGE, "academic_year": YEAR, "scheme_type": "Government"}
		)[1]
		self.assertEqual({r["aqar_clause"] for r in only}, {"5.1.1"})
		self.assertEqual(beneficiaries_report.execute({"company": TRUST})[1], [])
		govt = data_point("scholarship_govt_students", COLLEGE, YEAR)
		self.assertEqual(govt["value"], 2)
		self.assertEqual({r["name"] for r in govt["records"]}, {gov_a.name, gov_b.name})
		self.assertEqual(data_point("scholarship_inst_students", COLLEGE, YEAR)["value"], 1)
		self.assertEqual(data_point("scholarship_inst_students", TRUST, YEAR)["value"], 0)

	def test_a_student_with_two_government_schemes_counts_once(self):
		other = self.make_scheme("SCH Test Govt Two", "Government", self.college["bank"])
		self.application(self.a, self.govt)
		self.application(self.a, other)
		self.assertEqual(data_point("scholarship_govt_students", COLLEGE, YEAR)["value"], 1)


class TestSetup(CampusTestCase):
	def test_no_parallel_doctypes_and_the_config_fields_exist(self):
		self.assertFalse(
			frappe.db.exists("DocType", "Scholarship Disbursement")
			and frappe.get_meta("Scholarship Disbursement").is_submittable
		)
		self.assertFalse(frappe.db.exists("DocType", "Disbursement"))
		self.assertTrue(frappe.get_meta("Fee Category").has_field("oc_concession_allowed"))
		self.assertTrue(frappe.get_meta("Sales Invoice Item").has_field("oc_fee_concession"))
		self.assertTrue(frappe.db.exists("Approval Policy", {"document_type": "Fee Concession"}))

	def test_the_migrated_site_sanctions_scholarships_through_a_principal(self):
		policy = frappe.get_doc("Approval Policy", {"document_type": "Scholarship Application", "enabled": 1})
		self.assertEqual(
			[(l.approver_type, l.approver, l.scope_field) for l in policy.levels],
			[("Position", "PRINCIPAL", "company")],
		)

	def test_the_sanction_policy_is_seeded_only_when_the_college_has_none(self):
		drop_policies("Scholarship Application")
		seed_scholarship_policy()
		seed_scholarship_policy()
		self.assertEqual(
			frappe.get_all("Approval Policy", {"document_type": "Scholarship Application"}, pluck="name"),
			[SCHOLARSHIP_POLICY],
		)
		drop_policies("Scholarship Application")
		frappe.get_doc(
			{"doctype": "Approval Policy", "policy_name": "SCH Test Own Policy", "document_type": "Scholarship Application", "enabled": 0, "levels": [level("User", "Administrator")]}
		).insert()  # fmt: skip
		seed_scholarship_policy()  # even a disabled policy is the college's choice
		self.assertEqual(
			frappe.get_all("Approval Policy", {"document_type": "Scholarship Application"}, pluck="name"),
			["SCH Test Own Policy"],
		)


class TestFixRound1(ScholarshipFixture):
	def setUp(self):
		super().setUp()
		frappe.db.set_value("Fee Category", "Tuition", "oc_concession_allowed", 1)
		frappe.db.delete("Approval Level", {"parent": ["in", [POLICY, "Fee Concession Approval"]]})
		frappe.db.delete("Approval Policy", {"name": ["in", [POLICY, "Fee Concession Approval"]]})
		frappe.get_doc(
			{
				"doctype": "Approval Policy",
				"policy_name": POLICY,
				"document_type": "Fee Concession",
				"levels": [level("User", APPROVER, title="Principal")],
			}
		).insert()

	def approved(self, student=None, **values):
		doc = frappe.get_doc(
			{
				"doctype": "Fee Concession",
				"student": student or self.a,
				"academic_year": YEAR,
				"fee_category": "Tuition",
				"concession_type": "Percent",
				"percent": 10,
				"reason": "Merit",
				**values,
			}
		).insert()
		request = request_approval("Fee Concession", doc.name)
		frappe.set_user(APPROVER)
		approve(request, None)
		frappe.set_user("Administrator")
		return doc.reload()

	def draft_invoice(self, student=None, amount=10000):
		student = student or self.a
		invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": COLLEGE,
				"customer": frappe.db.get_value("Student", student, "customer"),
				"student": student,
				"posting_date": today(),
				"set_posting_time": 1,
				"due_date": add_days(today(), 15),
				"debit_to": frappe.db.get_value("Company", COLLEGE, "default_receivable_account"),
				"items": [{"item_code": category_for_type("Tuition"), "qty": 1, "rate": amount}],
			}
		)
		invoice.flags.ignore_permissions = True
		return invoice.insert()

	def test_cancelling_a_concession_clears_its_discount_from_draft_invoices(self):
		concession = self.approved()
		invoice = self.draft_invoice()
		self.assertEqual(invoice.grand_total, 9000)
		concession.reload().cancel()
		invoice.reload().save()  # validation strips the stale tag and the discount
		self.assertEqual((invoice.grand_total, invoice.items[0].oc_fee_concession), (10000, None))
		self.assertEqual(invoice.submit().grand_total, 10000)
		self.assertEqual(
			frappe.db.get_value("Fee Concession", concession.name, "status"), "Open"
		)  # not flipped to Applied

	def test_mark_applied_refuses_a_cancelled_or_foreign_concession(self):
		cancelled, foreign = self.approved(), self.approved(self.b)
		cancelled.reload().cancel()
		invoice = self.draft_invoice()
		for name in (cancelled.name, foreign.name):
			invoice.items[0].oc_fee_concession = name
			invoice.items[0].discount_amount = 1000
			with self.assertRaisesRegex(frappe.ValidationError, "cannot discount"):
				concessions.mark_applied(invoice)

	def test_another_students_tag_is_stripped_on_save(self):
		foreign = self.approved(self.b)
		invoice = self.draft_invoice()  # student a: nothing to apply
		invoice.items[0].oc_fee_concession = foreign.name
		invoice.items[0].price_list_rate, invoice.items[0].discount_amount, invoice.items[0].rate = (
			10000,
			1000,
			9000,
		)
		invoice.save()
		self.assertEqual((invoice.grand_total, invoice.items[0].oc_fee_concession), (10000, None))

	def test_two_drafts_one_concession_the_second_submits_cleanly_without_it(self):
		concession = self.approved()
		first, second = self.draft_invoice(), self.draft_invoice()
		self.assertEqual((first.grand_total, second.grand_total), (9000, 9000))
		first.submit()
		self.assertEqual(second.reload().submit().grand_total, 10000)
		self.assertEqual(
			frappe.db.get_value("Fee Concession", concession.name, "applied_invoice"), first.name
		)

	def test_a_category_unflagged_after_approval_is_no_longer_discounted(self):
		self.approved()
		frappe.db.set_value("Fee Category", "Tuition", "oc_concession_allowed", 0)
		self.assertEqual(self.draft_invoice().grand_total, 10000)

	def test_a_cancelled_and_amended_voucher_cannot_take_the_disbursement_past_the_sanction(self):
		self.owe(self.a, COLLEGE)
		application = self.application(self.a, self.govt)
		row = scholarships.disburse(application.name, 50000)
		payment = frappe.get_doc("Payment Entry", row["voucher"])
		payment.cancel()
		amended = frappe.copy_doc(payment)
		amended.amended_from, amended.docstatus = payment.name, 0
		with self.assertRaisesRegex(frappe.ValidationError, "Disburse"):
			amended.insert()
		scholarships.disburse(application.name, 50000)  # the sanction is still whole after the cancel
		with self.assertRaises(frappe.ValidationError):
			scholarships.disburse(application.name, 1)

	def test_a_scholarship_payment_entry_takes_no_fee_receipt_number(self):
		self.owe(self.a, COLLEGE)
		application = self.application(self.a, self.govt)
		row = scholarships.disburse(application.name, 10000)
		self.assertFalse(frappe.db.get_value("Payment Entry", row["voucher"], "oc_receipt_no"))

	def test_the_receivable_comes_from_the_party_account(self):
		self.owe(self.a, COLLEGE)
		customer = frappe.db.get_value("Student", self.a, "customer")
		with patch(
			"campus.campus_finance.scholarships.get_party_account", return_value=self.college_receivable()
		) as account:
			scholarships.disburse(self.application(self.a, self.govt).name, 100)
		account.assert_called_with("Customer", customer, COLLEGE)

	def college_receivable(self):
		return frappe.db.get_value("Company", COLLEGE, "default_receivable_account")

	def test_the_beneficiaries_report_respects_user_permissions(self):
		self.application(self.a, self.govt)
		frappe.set_user(PLAIN)  # an Academics User with no read right on Scholarship Application
		with self.assertRaises(frappe.PermissionError):
			beneficiaries_report.execute({"company": COLLEGE, "academic_year": YEAR})

	def test_a_renewal_needs_an_earlier_year_than_the_application_it_renews(self):
		scheme = self.make_scheme("SCH Test Renewable", "Institutional", self.expense, renewable=1)
		first = self.application(self.b, scheme)
		renewal = frappe.get_doc(
			{
				"doctype": "Scholarship Application",
				"student": self.b,
				"scheme": scheme.name,
				"academic_year": YEAR,
				"application_type": "Renewal",
				"previous_application": first.name,
			}
		)
		with (
			patch.object(type(renewal), "check_duplicate"),
			self.assertRaisesRegex(frappe.ValidationError, "earlier academic year"),
		):
			renewal.insert()
