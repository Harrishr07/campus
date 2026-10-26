"""P1-T25 tests (M09-01): Fee Refund and caution deposit rules (unit), refund entries, the paid-amount cap, the dues set-off,
approval, and the Credit Note / refund Payment Entry builders Admission Cancellation shares."""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from frappe.tests import UnitTestCase
from frappe.utils import flt, today

from campus.campus_finance import api as finance
from campus.campus_finance import fee_refunds, refunds, scholarships
from campus.campus_finance.fee_heads import category_for_type
from campus.campus_platform.approvals import approve, request_approval
from campus.tests.approval_fixtures import approval_not_required, drop_policies, level
from campus.tests.factories import make_user
from campus.tests.finance_factories import (
	make_account,
	make_enrolled_students,
	make_finance_company,
	make_year_and_program,
)
from campus.tests.utils import CampusTestCase

COLLEGE, TRUST = "Refund Test College", "Refund Test Trust"
YEAR, PROGRAM = "Refund Test 2026", "Refund Test BE"
APPROVER, OTHER_COMPANY_USER = "rfd-approver@example.com", "rfd-other@example.com"
POLICY = "RFD Test Refund Policy"
TRUST_MANAGER, COLLEGE_MANAGER = "rfd-trust-mgr@example.com", "rfd-college-mgr@example.com"


class TestRules(UnitTestCase):
	def test_paid_for_head_is_the_receipts_in_the_heads_share(self):
		self.assertEqual(fee_refunds.paid_for_head(1000, "Tuition", {"Tuition": 500}), 1000)
		self.assertEqual(fee_refunds.paid_for_head(1000, "Tuition", {"Tuition": 400, "Exam": 600}), 400)
		self.assertEqual(fee_refunds.paid_for_head(1000, "Exam", {"Tuition": 400, "Exam": 600}), 600)
		self.assertEqual(fee_refunds.paid_for_head(0, "Tuition", {"Tuition": 100}), 0)
		self.assertEqual(fee_refunds.paid_for_head(333.33, "Tuition", {"Tuition": 50, "Exam": 50}), 166.67)
		self.assertEqual(
			fee_refunds.paid_for_head(333.33, "Exam", {"Tuition": 50, "Exam": 50}), 166.66
		)  # the remainder
		self.assertEqual(
			fee_refunds.paid_for_head(1000, "Fine", {"Tuition": 400}), 0
		)  # a head the invoice lacks

	def test_the_students_money_pays_the_caution_deposit_first(self):
		lines = {"Tuition": 50000, "Caution Deposit": 5000}
		self.assertEqual(fee_refunds.paid_for_head(5000, "Caution Deposit", lines), 5000)
		self.assertEqual(fee_refunds.paid_for_head(5000, "Tuition", lines), 0)
		self.assertEqual(fee_refunds.paid_for_head(3000, "Caution Deposit", lines), 3000)
		self.assertEqual(fee_refunds.paid_for_head(3000, "Tuition", lines), 0)
		self.assertEqual(fee_refunds.paid_for_head(20000, "Caution Deposit", lines), 5000)
		self.assertEqual(fee_refunds.paid_for_head(20000, "Tuition", lines), 15000)

	def test_the_other_heads_share_what_the_deposit_leaves_pro_rata(self):
		lines = {"Tuition": 6000, "Exam": 4000, "Caution Deposit": 2000}
		parts = [
			fee_refunds.paid_for_head(7000, head, lines) for head in ("Caution Deposit", "Tuition", "Exam")
		]
		self.assertEqual(parts, [2000, 3000, 2000])
		self.assertEqual(sum(parts), 7000)  # never more than the student paid
		self.assertEqual(fee_refunds.paid_for_head(5000, "Caution Deposit", {"Caution Deposit": 3000}), 3000)
		self.assertEqual(fee_refunds.paid_for_head(-100, "Caution Deposit", {"Caution Deposit": 3000}), 0)

	def test_available_is_paid_less_credit_notes_and_deductions(self):
		self.assertEqual(fee_refunds.available_to_refund(1000, 0, 0), 1000)
		self.assertEqual(fee_refunds.available_to_refund(1000, -300, 0), 700)
		self.assertEqual(fee_refunds.available_to_refund(1000, -300, 200), 500)
		self.assertEqual(fee_refunds.available_to_refund(1000, -900, 200), 0)

	def test_a_deposit_refund_is_the_deposit_less_damages(self):
		self.assertEqual(fee_refunds.caution_amount(5000, 0), 5000)
		self.assertEqual(fee_refunds.caution_amount(5000, 1200), 3800)
		self.assertEqual(fee_refunds.caution_amount(5000, 6000), 0)

	def test_set_off_takes_dues_before_cash(self):
		self.assertEqual(fee_refunds.set_off(5000, 0), (0, 5000))
		self.assertEqual(fee_refunds.set_off(5000, 2000), (2000, 3000))
		self.assertEqual(fee_refunds.set_off(5000, 9000), (5000, 0))
		self.assertEqual(fee_refunds.set_off(5000, -400), (0, 5000))


class RefundFixture(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.college = make_finance_company(COLLEGE, "RFDC")
		cls.trust = make_finance_company(TRUST, "RFDT")
		if not frappe.db.exists("Party Type", "Customer"):
			frappe.get_doc(
				{"doctype": "Party Type", "party_type": "Customer", "account_type": "Receivable"}
			).insert()
		make_year_and_program(COLLEGE, PROGRAM, YEAR)
		_group, cls.students = make_enrolled_students(COLLEGE, PROGRAM, YEAR, 2, "RfdStu")
		cls.a, cls.b = cls.students
		make_user(APPROVER, [COLLEGE, TRUST])
		make_user(OTHER_COMPANY_USER, [TRUST])
		for user in (APPROVER, OTHER_COMPANY_USER):
			frappe.get_doc("User", user).add_roles("Accounts User")

	def setUp(self):
		frappe.db.savepoint("refund_test")
		self.addCleanup(frappe.db.rollback, save_point="refund_test")
		self.addCleanup(frappe.set_user, "Administrator")
		for company in (COLLEGE, TRUST):  # a bare test site has no bank account default
			frappe.db.set_value(
				"Company",
				company,
				"default_bank_account",
				self.college["bank"] if company == COLLEGE else self.trust["bank"],
			)
		for company, accounts in ((COLLEGE, self.college), (TRUST, self.trust)):
			frappe.db.set_value("Company", company, "oc_damages_income_account", accounts["income"])
		frappe.db.delete("Approval Level", {"parent": ["in", [POLICY, "Fee Refund Approval"]]})
		frappe.db.delete("Approval Policy", {"name": ["in", [POLICY, "Fee Refund Approval"]]})
		frappe.get_doc(
			{
				"doctype": "Approval Policy",
				"policy_name": POLICY,
				"document_type": "Fee Refund",
				"levels": [level("User", APPROVER, title="Accounts")],
			}
		).insert()

	def invoice(self, student, head, amount, company=COLLEGE, paid=True):
		invoice = finance.raise_fee_invoice(student, head, amount, company, "Refund test")
		if paid:
			self.pay(invoice.name)
		return invoice

	def pay(self, invoice, amount=None):
		payment = get_payment_entry("Sales Invoice", invoice, party_amount=amount)
		payment.reference_no, payment.reference_date = "UTR1", today()
		payment.insert().submit()

	def two_head_invoice(
		self, student, company=COLLEGE, heads=(("Tuition", 6000), ("Exam", 4000)), paid=True
	):
		"""An invoice of the heads (Tuition 6000 and Exam 4000 by default), paid in full when `paid`."""
		invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": company,
				"customer": frappe.db.get_value("Student", student, "customer"),
				"student": student,
				"posting_date": today(),
				"set_posting_time": 1,
				"due_date": today(),
				"debit_to": frappe.db.get_value("Company", company, "default_receivable_account"),
				"items": [
					{"item_code": category_for_type(head), "qty": 1, "rate": rate} for head, rate in heads
				],
			}
		)
		invoice.flags.ignore_permissions = True
		invoice.insert().submit()
		if paid:
			self.pay(invoice.name)
		return invoice

	def refund(self, invoice, student=None, **values):
		values = {
			"refund_type": "Fee Refund",
			"fee_head": "Tuition",
			"amount": 1000,
			"reason": "Course withdrawn",
			**values,
		}
		return frappe.get_doc(
			{"doctype": "Fee Refund", "student": student or self.a, "fee_invoice": invoice.name, **values}
		).insert()

	def approved(self, doc):
		request = request_approval("Fee Refund", doc.name)
		frappe.set_user(APPROVER)
		approve(request, None)
		frappe.set_user("Administrator")
		return doc.reload()

	def gl(self, voucher):
		rows = frappe.get_all(
			"GL Entry", {"voucher_no": voucher, "is_cancelled": 0}, ["account", "debit", "credit"]
		)
		return {r.account: (flt(r.debit), flt(r.credit)) for r in rows}

	def outstanding(self, invoice):
		return flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount"))


class TestFeeRefund(RefundFixture):
	def test_an_approved_refund_posts_a_credit_note_and_drafts_the_payment(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		doc = self.approved(self.refund(invoice, amount=4000))
		self.assertEqual(
			(doc.docstatus, doc.company, flt(doc.available), flt(doc.cash_refund), flt(doc.dues_netted)),
			(1, COLLEGE, 10000, 4000, 0),
		)
		note = frappe.get_doc("Sales Invoice", doc.credit_note)
		self.assertEqual(
			(note.docstatus, note.is_return, note.return_against, note.company, flt(note.grand_total)),
			(1, 1, invoice.name, COLLEGE, -4000),
		)
		entries = self.gl(note.name)
		self.assertEqual(entries["Sales - RFDC"], (4000, 0))  # income reversed
		self.assertEqual(sum(d for d, _c in entries.values()), sum(c for _d, c in entries.values()))
		payment = frappe.get_doc("Payment Entry", doc.payment_entry)
		self.assertEqual(
			(payment.docstatus, payment.payment_type, flt(payment.paid_amount), payment.paid_from),
			(0, "Pay", 4000, self.college["bank"]),
		)
		self.assertEqual([r.reference_name for r in payment.references], [note.name])

	def test_the_refund_needs_approval_and_cannot_approve_itself(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		doc = self.refund(invoice)
		with self.assertRaisesRegex(frappe.ValidationError, "needs approval"):
			doc.submit()
		request = request_approval("Fee Refund", doc.name)  # Administrator is the owner and requester
		with self.assertRaises(frappe.PermissionError):
			approve(request, None)
		self.assertEqual(frappe.db.get_value("Fee Refund", doc.name, "docstatus"), 0)

	def test_the_seeded_policy_asks_an_accounts_manager(self):
		from campus.campus_finance.setup import REFUND_POLICY, seed_refund_policy

		frappe.db.delete("Approval Level", {"parent": POLICY})
		frappe.db.delete("Approval Policy", {"name": POLICY})
		seed_refund_policy()
		seed_refund_policy()  # idempotent
		policy = frappe.get_doc("Approval Policy", {"document_type": "Fee Refund"})
		self.assertEqual(policy.name, REFUND_POLICY)
		self.assertEqual(
			[(l.approver_type, l.approver) for l in policy.levels], [("Role", "Accounts Manager")]
		)

	def test_a_refund_cannot_exceed_what_was_paid_for_the_head(self):
		invoice = self.two_head_invoice(self.a)
		with self.assertRaisesRegex(frappe.ValidationError, "6000.0 of the Tuition"):
			self.refund(invoice, amount=6001)
		self.assertEqual(self.approved(self.refund(invoice, amount=6000)).docstatus, 1)
		self.assertEqual(
			fee_refunds.balance(invoice.name, "Exam").available, 4000
		)  # the other head is untouched
		with self.assertRaisesRegex(frappe.ValidationError, "already been refunded"):
			self.refund(invoice)

	def test_only_money_received_can_be_refunded(self):
		invoice = self.invoice(self.a, "Tuition", 10000, paid=False)
		frappe.db.set_value(
			"Sales Invoice", invoice.name, "outstanding_amount", 0
		)  # settled otherwise, e.g. a waiver
		with self.assertRaisesRegex(frappe.ValidationError, "nothing to refund"):
			self.refund(invoice)

	def test_a_part_paid_invoice_gives_no_refund(self):
		invoice = self.invoice(self.a, "Tuition", 10000, paid=False)
		self.pay(invoice.name, 3000)
		with self.assertRaisesRegex(frappe.ValidationError, "7000.0 unpaid"):
			self.refund(invoice, amount=3000)

	def test_credit_notes_already_issued_count_against_the_cap(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		finance.make_credit_note(
			frappe.get_doc("Sales Invoice", invoice.name), 7000
		)  # accounts issued it by hand
		self.assertEqual(fee_refunds.balance(invoice.name, "Tuition").available, 3000)
		with self.assertRaisesRegex(frappe.ValidationError, "3000.0 of the Tuition"):
			self.refund(invoice, amount=3001)

	def test_a_head_is_refunded_once(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		self.approved(self.refund(invoice, amount=7000))
		with self.assertRaisesRegex(frappe.ValidationError, "already been refunded"):
			self.refund(invoice, amount=1000)

	def test_two_refunds_drafted_together_cannot_both_pass_at_submit(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		first, second = (
			self.refund(invoice, amount=7000),
			self.refund(invoice, amount=7000),
		)  # each passes alone
		self.approved(first)
		with self.assertRaisesRegex(frappe.ValidationError, "already been refunded"):
			self.approved(second)
		self.assertEqual(frappe.db.get_value("Fee Refund", second.name, "docstatus"), 0)

	def test_a_refund_drafted_before_an_accounts_credit_note_is_held_to_the_cap_at_submit(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		draft = self.refund(invoice, amount=7000)
		finance.make_credit_note(frappe.get_doc("Sales Invoice", invoice.name), 5000)
		with self.assertRaisesRegex(frappe.ValidationError, "5000.0 of the Tuition"):
			self.approved(draft)

	def test_submit_locks_the_invoice_then_reads_the_balance_with_locking_reads(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		doc = self.refund(invoice, amount=1000)
		order = []
		real_get_value, real_balance = frappe.db.get_value, fee_refunds.balance

		def spy_get_value(doctype, filters=None, fieldname="name", *args, **kwargs):
			if doctype == "Sales Invoice" and kwargs.get("for_update") and fieldname == "name":
				order.append("lock")
			return real_get_value(doctype, filters, fieldname, *args, **kwargs)

		def spy_balance(*args, **kwargs):
			order.append(("balance", kwargs.get("locking")))
			return real_balance(*args, **kwargs)

		with (
			patch.object(frappe.db, "get_value", spy_get_value),
			patch.object(fee_refunds, "balance", spy_balance),
		):
			self.approved(doc)
		self.assertEqual(order[order.index("lock") + 1], ("balance", True))

	def test_a_refund_of_a_head_the_invoice_lacks_is_refused(self):
		invoice = self.invoice(self.a, "Exam", 2000)
		with self.assertRaisesRegex(frappe.ValidationError, "no Tuition line"):
			self.refund(invoice)

	def test_a_refund_of_another_students_invoice_is_refused(self):
		invoice = self.invoice(self.b, "Tuition", 10000)
		with self.assertRaisesRegex(frappe.ValidationError, "not an invoice of student"):
			self.refund(invoice, student=self.a)

	def test_an_unpermitted_company_cannot_be_refunded(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		frappe.set_user(OTHER_COMPANY_USER)
		with self.assertRaises(frappe.PermissionError):
			self.refund(invoice)

	def test_an_admission_cancelled_invoice_is_not_refunded_twice(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		cancellation = frappe.new_doc("Admission Cancellation")
		cancellation.update({"name": "RFD-AC-1", "docstatus": 1, "fee_invoice": invoice.name})
		cancellation.db_insert()
		with self.assertRaisesRegex(frappe.ValidationError, "Admission Cancellation"):
			self.refund(invoice)

	def test_cancelling_a_refund_reverses_its_vouchers_and_restores_the_cap(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		doc = self.approved(self.refund(invoice, amount=4000))
		payment, note = doc.payment_entry, doc.credit_note
		self.assertEqual(fee_refunds.balance(invoice.name, "Tuition").available, 6000)
		doc.cancel()
		self.assertEqual(
			(
				frappe.db.get_value("Fee Refund", doc.name, "docstatus"),
				frappe.db.get_value("Sales Invoice", note, "docstatus"),
			),
			(2, 2),
		)
		self.assertFalse(frappe.db.exists("Payment Entry", payment))  # the draft is deleted
		self.assertIsNone(frappe.db.get_value("Fee Refund", doc.name, "payment_entry"))
		self.assertEqual(fee_refunds.balance(invoice.name, "Tuition").available, 10000)
		self.assertEqual(self.outstanding(invoice.name), 0)
		self.assertEqual(self.approved(self.refund(invoice, amount=10000)).docstatus, 1)  # refundable again

	def test_a_refund_whose_payment_was_made_cannot_be_cancelled(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		doc = self.approved(self.refund(invoice, amount=4000))
		payment = self.submit_payment(doc)
		with self.assertRaisesRegex(frappe.ValidationError, f"cancel Payment Entry {payment.name}"):
			doc.cancel()
		self.assertEqual(fee_refunds.balance(invoice.name, "Tuition").available, 6000)  # the cap is not freed

	def test_after_accounts_cancels_the_payment_the_refund_can_be_cancelled(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		doc = self.approved(self.refund(invoice, amount=4000))
		self.submit_payment(doc).cancel()
		doc.reload().cancel()
		self.assertEqual(frappe.db.get_value("Sales Invoice", doc.credit_note, "docstatus"), 2)
		self.assertEqual(fee_refunds.balance(invoice.name, "Tuition").available, 10000)

	def test_a_refund_paid_by_an_amended_payment_cannot_be_cancelled(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		doc = self.approved(self.refund(invoice, amount=4000))
		original = self.submit_payment(doc)
		original.cancel()
		amended = frappe.copy_doc(original)
		amended.amended_from, amended.docstatus = original.name, 0
		amended.insert().submit()
		with self.assertRaisesRegex(frappe.ValidationError, f"cancel Payment Entry {amended.name}"):
			doc.reload().cancel()
		self.assertEqual(frappe.db.get_value("Sales Invoice", doc.credit_note, "docstatus"), 1)
		self.assertEqual(fee_refunds.balance(invoice.name, "Tuition").available, 6000)  # the cap is not freed

	def test_a_refund_paid_by_another_accounts_payment_cannot_be_cancelled(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		doc = self.approved(self.refund(invoice, amount=4000))
		payment = get_payment_entry("Sales Invoice", doc.credit_note)
		payment.reference_no, payment.reference_date = "BANKREF2", today()
		payment.insert().submit()
		with self.assertRaisesRegex(frappe.ValidationError, f"cancel Payment Entry {payment.name}"):
			doc.cancel()
		self.assertEqual(fee_refunds.balance(invoice.name, "Tuition").available, 6000)

	def test_a_refund_paid_by_a_journal_entry_cannot_be_cancelled(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		doc = self.approved(self.refund(invoice, amount=4000))
		note = frappe.get_doc("Sales Invoice", doc.credit_note)
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry", "voucher_type": "Bank Entry", "company": COLLEGE, "posting_date": today(),
				"cheque_no": "BANKREF3", "cheque_date": today(),
				"accounts": [
					{"account": note.debit_to, "party_type": "Customer", "party": note.customer, "debit_in_account_currency": 4000,
					 "reference_type": "Sales Invoice", "reference_name": note.name},
					{"account": self.college["bank"], "credit_in_account_currency": 4000},
				],
			}
		).insert()  # fmt: skip
		entry.submit()
		with self.assertRaisesRegex(frappe.ValidationError, f"cancel Journal Entry {entry.name}"):
			doc.cancel()
		self.assertEqual(fee_refunds.balance(invoice.name, "Tuition").available, 6000)

	def test_cancel_reads_the_payments_of_the_credit_note_with_locking_reads(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		doc = self.approved(self.refund(invoice, amount=4000))
		real_sql, queries = frappe.db.sql, []

		def spy_sql(query, *args, **kwargs):
			queries.append(str(query).lower())
			return real_sql(query, *args, **kwargs)

		with patch.object(frappe.db, "sql", spy_sql):
			doc.cancel()
		for table in ("payment entry reference", "journal entry account"):
			first = next(q for q in queries if q.lstrip().startswith("select") and table in q)
			self.assertTrue(first.rstrip().endswith("for update"), first)

	def submit_payment(self, doc):
		payment = frappe.get_doc("Payment Entry", doc.payment_entry)
		payment.reference_no, payment.reference_date = "BANKREF1", today()
		payment.save().submit()
		return payment

	def test_the_drafted_refund_payment_submits_and_settles_the_credit_note(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		doc = self.approved(self.refund(invoice, amount=4000))
		self.assertEqual(self.outstanding(doc.credit_note), -4000)  # the credit waits for the payment
		payment = self.submit_payment(doc)
		self.assertEqual(payment.docstatus, 1)
		self.assertEqual(self.outstanding(doc.credit_note), 0)
		self.assertEqual(self.outstanding(invoice.name), 0)
		self.assertEqual(self.gl(payment.name)[self.college["bank"]], (0, 4000))

	def test_the_seeded_policy_limits_approvers_to_the_company(self):
		from campus.campus_finance.setup import seed_refund_policy

		frappe.db.delete("Approval Level", {"parent": POLICY})
		frappe.db.delete("Approval Policy", {"name": POLICY})
		seed_refund_policy()
		self.assertEqual(
			frappe.get_doc("Approval Policy", {"document_type": "Fee Refund"}).levels[0].limit_to_company, 1
		)
		for email, company in ((TRUST_MANAGER, TRUST), (COLLEGE_MANAGER, COLLEGE)):
			make_user(email, [company])
			frappe.get_doc("User", email).add_roles("Accounts Manager", "Accounts User")
		request = request_approval(
			"Fee Refund", self.refund(self.invoice(self.a, "Tuition", 10000), amount=1000).name
		)
		frappe.set_user(TRUST_MANAGER)
		with self.assertRaises(frappe.PermissionError):
			approve(request, None)
		frappe.set_user(COLLEGE_MANAGER)
		approve(request, None)

	def test_the_caution_deposit_head_is_refunded_only_as_a_caution_deposit_refund(self):
		invoice = self.invoice(self.a, "Caution Deposit", 5000)
		with self.assertRaisesRegex(frappe.ValidationError, "Caution Deposit refund"):
			self.refund(invoice, fee_head="Caution Deposit", amount=5000)

	def test_damages_of_the_deposit_do_not_reduce_another_head(self):
		invoice = self.two_head_invoice(self.a, heads=(("Caution Deposit", 5000), ("Tuition", 6000)))
		self.approved(
			self.refund(
				invoice, refund_type="Caution Deposit", fee_head="Caution Deposit", amount=0, deduction=500
			)
		)
		self.assertEqual(fee_refunds.balance(invoice.name, "Tuition").available, 6000)

	def test_partial_head_refunds_need_one_tax_treatment_on_the_invoice(self):
		same = SimpleNamespace(
			name="INV",
			taxes=[1],
			items=[
				SimpleNamespace(item_code="A", item_tax_template="T", item_tax_rate="{}"),
				SimpleNamespace(item_code="B", item_tax_template="T", item_tax_rate="{}"),
			],
		)
		refunds.check_uniform_tax(same, {"A"})
		mixed = SimpleNamespace(
			name="INV",
			taxes=[1],
			items=[
				SimpleNamespace(item_code="A", item_tax_template="T", item_tax_rate="{}"),
				SimpleNamespace(item_code="B", item_tax_template=None, item_tax_rate="{}"),
			],
		)
		with self.assertRaisesRegex(frappe.ValidationError, "different taxes"):
			refunds.check_uniform_tax(mixed, {"A"})
		refunds.check_uniform_tax(mixed, {"A", "B"})  # the whole invoice
		mixed.taxes = []
		refunds.check_uniform_tax(mixed, {"A"})  # no taxes to apportion

	def test_an_admission_invoice_is_refunded_by_admission_cancellation(self):
		invoice = self.invoice(self.a, "Tuition", 10000)
		enrollment = frappe.db.get_value("Program Enrollment", {"student": self.a})
		frappe.db.set_value("Sales Invoice", invoice.name, "oc_program_enrollment", enrollment)
		with self.assertRaisesRegex(frappe.ValidationError, "Admission Cancellation"):
			self.refund(invoice)


class TestCautionDeposit(RefundFixture):
	def deposit(self, student, amount=5000, company=COLLEGE):
		return self.invoice(student, "Caution Deposit", amount, company)

	def caution(self, invoice, **values):
		values = {
			"refund_type": "Caution Deposit",
			"fee_head": "Caution Deposit",
			"amount": 0,
			"reason": "Course completed",
			**values,
		}
		return self.refund(invoice, **values)

	def test_the_deposit_comes_back_less_damages(self):
		invoice = self.deposit(self.a)
		doc = self.approved(self.caution(invoice, deduction=500))
		self.assertEqual(
			(flt(doc.amount), flt(doc.deduction), flt(doc.dues_netted), flt(doc.cash_refund)),
			(4500, 500, 0, 4500),
		)
		note = frappe.get_doc("Sales Invoice", doc.credit_note)
		self.assertEqual(flt(note.grand_total), -4500)
		self.assertEqual(
			self.gl(note.name)[self.college["deposit"]], (4500, 0)
		)  # the deposit liability is released
		self.assertEqual(flt(frappe.db.get_value("Payment Entry", doc.payment_entry, "paid_amount")), 4500)

	def test_damages_move_from_the_deposit_liability_to_income(self):
		invoice = self.deposit(self.a)
		doc = self.approved(self.caution(invoice, deduction=500))
		entry = frappe.get_doc("Journal Entry", doc.damages_entry)
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual(
			self.gl(entry.name), {self.college["deposit"]: (500, 0), self.college["income"]: (0, 500)}
		)

	def test_damages_need_an_income_account_for_the_company(self):
		frappe.db.set_value("Company", COLLEGE, "oc_damages_income_account", None)
		invoice = self.deposit(self.a)
		with self.assertRaisesRegex(frappe.ValidationError, "damages income account"):
			self.approved(self.caution(invoice, deduction=500))
		frappe.set_user("Administrator")
		self.approved(self.caution(invoice))  # no damages, no account needed

	def test_cancelling_a_deposit_refund_reverses_the_set_off_and_the_damages(self):
		invoice = self.deposit(self.a)
		dues = finance.raise_fee_invoice(self.a, "Tuition", 3000, COLLEGE, "Dues")
		doc = self.approved(self.caution(invoice, deduction=500))
		self.assertEqual(self.outstanding(dues.name), 0)
		doc.cancel()
		self.assertEqual(self.outstanding(dues.name), 3000)
		for entry in (doc.adjustment_entry, doc.damages_entry):
			self.assertEqual(frappe.db.get_value("Journal Entry", entry, "docstatus"), 2)
		self.assertEqual(fee_refunds.balance(invoice.name, "Caution Deposit").available, 5000)

	def test_damages_count_against_the_cap_and_the_rest_stays_in_the_liability(self):
		invoice = self.deposit(self.a)
		self.approved(self.caution(invoice, deduction=500))
		self.assertEqual(fee_refunds.balance(invoice.name, "Caution Deposit").available, 0)

	def test_a_refund_with_damages_above_the_deposit_is_refused(self):
		invoice = self.deposit(self.a)
		with self.assertRaisesRegex(frappe.ValidationError, "nothing to refund"):
			self.caution(invoice, deduction=5000)

	def test_dues_of_the_company_are_set_off_before_cash(self):
		invoice = self.deposit(self.a)
		dues = finance.raise_fee_invoice(self.a, "Tuition", 3000, COLLEGE, "Dues")
		self.assertEqual(finance.has_dues(self.a, companies=[COLLEGE]).blocking, 3000)
		doc = self.approved(self.caution(invoice, deduction=500))
		self.assertEqual((flt(doc.amount), flt(doc.dues_netted), flt(doc.cash_refund)), (4500, 3000, 1500))
		self.assertEqual(self.outstanding(dues.name), 0)
		self.assertEqual(finance.has_dues(self.a, companies=[COLLEGE]).blocking, 0)
		entry = frappe.get_doc("Journal Entry", doc.adjustment_entry)
		self.assertEqual((entry.docstatus, entry.company, flt(entry.total_debit)), (1, COLLEGE, 3000))
		self.assertEqual(flt(frappe.db.get_value("Payment Entry", doc.payment_entry, "paid_amount")), 1500)

	def test_dues_larger_than_the_deposit_leave_no_cash(self):
		invoice = self.deposit(self.a, 2000)
		dues = finance.raise_fee_invoice(self.a, "Tuition", 3000, COLLEGE, "Dues")
		doc = self.approved(self.caution(invoice))
		self.assertEqual((flt(doc.dues_netted), flt(doc.cash_refund), doc.payment_entry), (2000, 0, None))
		self.assertEqual(self.outstanding(dues.name), 1000)

	def test_dues_of_another_company_are_not_set_off(self):
		invoice = self.deposit(self.a, 5000, TRUST)
		college_dues = finance.raise_fee_invoice(self.a, "Tuition", 3000, COLLEGE, "Dues")
		doc = self.approved(self.caution(invoice))
		self.assertEqual((doc.company, flt(doc.dues_netted), flt(doc.cash_refund)), (TRUST, 0, 5000))
		self.assertEqual(self.outstanding(college_dues.name), 3000)
		self.assertEqual(frappe.db.get_value("Payment Entry", doc.payment_entry, "company"), TRUST)

	def test_another_students_dues_are_not_set_off(self):
		invoice = self.deposit(self.a)
		finance.raise_fee_invoice(self.b, "Tuition", 3000, COLLEGE, "Dues")
		self.assertEqual(flt(self.approved(self.caution(invoice)).dues_netted), 0)


class TestScholarshipMoneyIsNotRefunded(RefundFixture):
	"""A scholarship settles fees; it is not money the student paid, so a refund never pays it out."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.expense = make_account(
			COLLEGE, "RFDC", "Scholarship Expense", "Indirect Expenses", root_type="Expense"
		)

	def award(self, student, scheme_type, amount):
		"""Sanction and disburse `amount` of a Government (Payment Entry) or Institutional (Journal Entry) scheme."""
		name = f"RFD Test {scheme_type} Scheme"
		if not frappe.db.exists("Scholarship Scheme", name):
			account = self.college["bank"] if scheme_type == "Government" else self.expense
			frappe.get_doc(
				{"doctype": "Scholarship Scheme", "scheme_name": name, "company": COLLEGE, "scheme_type": scheme_type,
				 "account": account, "amount_type": "Fixed", "amount": amount}
			).insert()  # fmt: skip
		drop_policies(
			"Scholarship Application"
		)  # sanctioned by submitting; test_mandatory_approval covers the approval list
		with approval_not_required():
			application = frappe.get_doc(
				{"doctype": "Scholarship Application", "student": student, "scheme": name, "academic_year": YEAR}
			).insert().submit()  # fmt: skip
		return scholarships.disburse(application.name, amount, "SCH-UTR")

	def test_paid_by_the_student_leaves_out_both_kinds_of_scholarship(self):
		for scheme_type, student in (("Government", self.a), ("Institutional", self.b)):
			invoice = self.invoice(student, "Tuition", 10000, paid=False)
			self.award(student, scheme_type, 6000)
			self.pay(invoice.name)
			self.assertEqual(self.outstanding(invoice.name), 0)
			self.assertEqual(refunds.paid_by_student(invoice.name), 4000, scheme_type)

	def test_a_fee_refund_returns_only_what_the_student_paid(self):
		for scheme_type, student in (("Government", self.a), ("Institutional", self.b)):
			invoice = self.invoice(student, "Tuition", 10000, paid=False)
			self.award(student, scheme_type, 6000)
			self.pay(invoice.name)
			self.assertEqual(fee_refunds.balance(invoice.name, "Tuition").available, 4000, scheme_type)
			with self.assertRaisesRegex(frappe.ValidationError, "4000.0 of the Tuition"):
				self.refund(invoice, student, amount=4001)
			doc = self.approved(self.refund(invoice, student, amount=4000))
			self.assertEqual((doc.docstatus, flt(doc.cash_refund)), (1, 4000), scheme_type)

	def test_an_invoice_settled_by_a_scholarship_alone_has_nothing_to_refund(self):
		for scheme_type, student in (("Government", self.a), ("Institutional", self.b)):
			invoice = self.invoice(student, "Tuition", 6000, paid=False)
			self.award(student, scheme_type, 6000)
			self.assertEqual(self.outstanding(invoice.name), 0)
			with self.assertRaisesRegex(frappe.ValidationError, "nothing to refund"):
				self.refund(invoice, student)

	def test_a_caution_deposit_refund_holds_back_the_scholarship_share(self):
		invoice = self.invoice(self.a, "Caution Deposit", 5000, paid=False)
		self.award(self.a, "Government", 2000)
		self.pay(invoice.name)
		doc = self.approved(
			self.refund(
				invoice, refund_type="Caution Deposit", fee_head="Caution Deposit", amount=0, reason="Done"
			)
		)
		self.assertEqual((flt(doc.amount), flt(doc.cash_refund)), (3000, 3000))

	def test_the_students_own_money_refunds_the_caution_deposit_first(self):
		for scheme_type, student in (("Government", self.a), ("Institutional", self.b)):
			invoice = self.two_head_invoice(
				student, heads=(("Tuition", 50000), ("Caution Deposit", 5000)), paid=False
			)
			self.award(student, scheme_type, 50000)
			self.pay(invoice.name)
			self.assertEqual(
				(self.outstanding(invoice.name), refunds.paid_by_student(invoice.name)),
				(0, 5000),
				scheme_type,
			)
			self.assertEqual(fee_refunds.balance(invoice.name, "Tuition").available, 0, scheme_type)
			self.assertEqual(
				fee_refunds.balance(invoice.name, "Caution Deposit").available, 5000, scheme_type
			)
			doc = self.approved(
				self.refund(
					invoice,
					student,
					refund_type="Caution Deposit",
					fee_head="Caution Deposit",
					amount=0,
					reason="Done",
				)
			)
			self.assertEqual((flt(doc.amount), flt(doc.cash_refund)), (5000, 5000), scheme_type)
