"""P1-T23 tests (M09-01, M09-02): fee heads, structures, fine slabs and run, challans, bank import, receipts."""

import csv
import io
import time
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, today

from campus.campus_finance import api, bank_import, fines
from campus.campus_finance.fee_heads import CAUTION_DEPOSIT, FEE_HEADS, FINE, TUITION, set_item_default
from campus.campus_platform import bulk
from campus.tests.finance_factories import (
	make_challan_format,
	make_enrolled_students,
	make_fee_schedule,
	make_fee_structure,
	make_company_with_accounts,
	make_finance_company,
	make_year_and_program,
)
from campus.tests.utils import CampusTestCase

COLLEGE = "Fee Test College"
OTHER_COLLEGE = "Fee Test Bare College"
YEAR = "Fee Test 2026"
PROGRAM = "Fee Test BE"
STUDENT_COUNT = 120
TUITION_FEE, EXAM_FEE, DEPOSIT = 40000, 2000, 5000
LATE_BY = 30  # the schedule's invoices are due this many days before today


def slab(from_day, to_day=0, amount=0, percent=0, per_day=0):
	return SimpleNamespace(from_day=from_day, to_day=to_day, amount=amount, percent=percent, per_day=per_day)


class TestFineCalculation(CampusTestCase):
	"""The pure fine functions: every branch."""

	def test_late_days_apply_the_grace_period_and_never_go_negative(self):
		self.assertEqual(fines.late_days("2026-01-01", "2026-01-11", 3), 7)
		self.assertEqual(fines.late_days("2026-01-01", "2026-01-04", 3), 0)
		self.assertEqual(fines.late_days("2026-01-10", "2026-01-01", 0), 0)  # not yet due

	def test_slabs_crossed_are_those_started_in_order(self):
		slabs = [slab(11, 30), slab(1, 10), slab(31)]
		self.assertEqual(fines.slabs_crossed(0, slabs), [])
		self.assertEqual([s.from_day for s in fines.slabs_crossed(1, slabs)], [1])
		self.assertEqual([s.from_day for s in fines.slabs_crossed(10, slabs)], [1])
		self.assertEqual([s.from_day for s in fines.slabs_crossed(11, slabs)], [1, 11])
		self.assertEqual([s.from_day for s in fines.slabs_crossed(500, slabs)], [1, 11, 31])

	def test_slab_amount_flat_percent_and_per_day(self):
		self.assertEqual(fines.slab_amount(slab(1, 10, amount=100), 40000), 100)
		self.assertEqual(fines.slab_amount(slab(1, 10, percent=2.5), 40000), 1000)
		self.assertEqual(fines.slab_amount(slab(11, 20, amount=10, per_day=1), 40000), 100)  # 10 days
		self.assertEqual(fines.slab_amount(slab(1, 5, percent=1, per_day=1), 1000), 50)  # 5 days of 1%

	def test_rule_validation_rejects_bad_slabs(self):
		def rule(*slabs, **values):
			return frappe.get_doc(
				{
					"doctype": "Fine Rule", "company": COLLEGE, "enabled": 0,
					"slabs": [dict(from_day=s.from_day, to_day=s.to_day, amount=s.amount, percent=s.percent, per_day=s.per_day) for s in slabs],
					**values,
				}
			)

		good = rule(slab(1, 10, amount=50), slab(11, 0, percent=1))
		good.validate()  # no error
		for bad in (
			rule(slab(0, 5, amount=50)),  # starts before day 1
			rule(slab(5, 3, amount=50)),  # ends before it starts
			rule(slab(1, 5)),  # neither amount nor percent
			rule(slab(1, 5, amount=5, percent=1)),  # both
			rule(slab(1, 0, amount=5, per_day=1)),  # per-day needs an end
			rule(slab(1, 10, amount=5), slab(10, 20, amount=5)),  # overlap
			rule(slab(1, 0, amount=5), slab(10, 20, amount=5)),  # open-ended slab not last
		):
			with self.assertRaises(frappe.ValidationError):
				bad.validate()


class FinanceTestCase(CampusTestCase):
	"""One college, 120 enrolled students and a submitted fee schedule with 120 invoices (built once)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.original_settings = frappe.db.get_value(
			"Education Settings", None, ["auto_submit_sales_invoice", "sales_invoice_posting_date_fee_schedule", "create_so"], as_dict=True
		)
		frappe.db.set_single_value(
			"Education Settings",
			{"auto_submit_sales_invoice": 1, "sales_invoice_posting_date_fee_schedule": 1, "create_so": 0},
		)
		cls.accounts = make_finance_company(COLLEGE, "FTC")
		make_company_with_accounts(OTHER_COLLEGE, "FTB")  # no Challan Format, no fee defaults
		make_year_and_program(COLLEGE, PROGRAM, YEAR)
		cls.group, cls.students = make_enrolled_students(COLLEGE, PROGRAM, YEAR, STUDENT_COUNT, "FeeStu")
		cls.structure = make_fee_structure(
			COLLEGE, PROGRAM, YEAR, {TUITION: TUITION_FEE, "Exam": EXAM_FEE, CAUTION_DEPOSIT: DEPOSIT}, cls.accounts
		)
		cls.schedule = make_fee_schedule(cls.structure, cls.group, due_date=add_days(today(), -LATE_BY), submit=False)
		cls.schedule.posting_date = add_days(today(), -LATE_BY - 5)
		cls.schedule.save().submit()
		started = time.monotonic()
		from education.education.doctype.fee_schedule.fee_schedule import generate_fees

		generate_fees(cls.schedule.name)
		cls.generation_seconds = time.monotonic() - started
		print(f"\nfee schedule generation of {STUDENT_COUNT} invoices: {cls.generation_seconds:.1f}s")
		cls.invoices = frappe.get_all(
			"Sales Invoice", {"fee_schedule": cls.schedule.name}, ["name", "student", "oc_challan_no", "due_date"], order_by="name"
		)

	@classmethod
	def tearDownClass(cls):
		frappe.db.set_single_value("Education Settings", cls.original_settings)
		super().tearDownClass()

	def setUp(self):
		frappe.db.savepoint("finance_test")
		self.addCleanup(frappe.db.rollback, save_point="finance_test")
		self.make_fine_rule()

	def make_fine_rule(self):
		"""Grace 5 days; 100 flat for days 1-10, 1% for 11-30, 500 flat from day 31."""
		frappe.db.delete("Fine Rule")  # savepoint-scoped: restored with the rollback
		self.rule = frappe.get_doc(
			{
				"doctype": "Fine Rule", "company": COLLEGE, "grace_days": 5,
				"slabs": [
					{"from_day": 1, "to_day": 10, "amount": 100},
					{"from_day": 11, "to_day": 30, "percent": 1},
					{"from_day": 31, "to_day": 0, "amount": 500},
				],
			}
		).insert()
		self.due = add_days(today(), -LATE_BY)

	def invoice(self, n=0):
		return frappe.get_doc("Sales Invoice", self.invoices[n].name)

	def make_invoice(self, student, item=TUITION, rate=1000, due_in=0, company=COLLEGE):
		customer = frappe.db.get_value("Student", student, "customer")
		invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice", "company": company, "customer": customer, "student": student,
				"posting_date": today(), "due_date": add_days(today(), due_in),
				"items": [{"item_code": item, "qty": 1, "rate": rate}],
			}
		).insert()
		return invoice.submit()


class FeeHeadTests:
	def test_twelve_heads_are_seeded_with_items_and_flags(self):
		for head, (refundable, gst) in FEE_HEADS.items():
			category = frappe.get_doc("Fee Category", head)
			self.assertEqual(
				(category.oc_fee_head_type, category.oc_refundable, category.oc_gst_applicable), (head, refundable, gst), head
			)
			self.assertEqual(category.item, head)
			item = frappe.get_doc("Item", head)
			self.assertEqual((item.is_stock_item, item.is_sales_item), (0, 1), head)  # a service
		self.assertEqual(len(FEE_HEADS), 12)

	def test_seeding_is_idempotent(self):
		from campus.campus_finance.setup import setup_finance

		before = frappe.db.count("Fee Category"), frappe.db.count("Item")
		setup_finance()
		self.assertEqual((frappe.db.count("Fee Category"), frappe.db.count("Item")), before)

	def test_item_defaults_carry_the_company_account_and_cost_centre(self):
		defaults = {
			d.company: d for d in frappe.get_doc("Item", TUITION).item_defaults
		}[COLLEGE]
		self.assertEqual((defaults.income_account, defaults.selling_cost_center), (self.accounts["income"], self.accounts["cost_center"]))
		deposit = {d.company: d for d in frappe.get_doc("Item", CAUTION_DEPOSIT).item_defaults}[COLLEGE]
		self.assertEqual(deposit.income_account, self.accounts["deposit"])

	def test_caution_deposit_default_must_be_a_liability_account(self):
		with self.assertRaises(frappe.ValidationError):
			set_item_default(CAUTION_DEPOSIT, COLLEGE, self.accounts["income"], self.accounts["cost_center"])

	def test_caution_deposit_is_always_refundable(self):
		frappe.db.set_value("Fee Category", CAUTION_DEPOSIT, "oc_refundable", 0)
		frappe.get_doc("Fee Category", CAUTION_DEPOSIT).save()
		self.assertEqual(frappe.db.get_value("Fee Category", CAUTION_DEPOSIT, "oc_refundable"), 1)

	def test_invoice_cannot_post_a_caution_deposit_to_income(self):
		student = self.students[0]
		invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice", "company": COLLEGE, "customer": frappe.db.get_value("Student", student, "customer"),
				"student": student, "posting_date": today(), "due_date": today(),
				"items": [{"item_code": CAUTION_DEPOSIT, "qty": 1, "rate": 100, "income_account": self.accounts["income"]}],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			invoice.insert()

	def test_fee_structure_needs_a_liability_default_for_a_caution_deposit(self):
		structure = frappe.get_doc(
			{
				"doctype": "Fee Structure", "company": OTHER_COLLEGE, "program": PROGRAM, "academic_year": YEAR,
				"components": [{"fees_category": CAUTION_DEPOSIT, "amount": 100}],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			structure.insert()

	def test_caution_deposit_credits_a_liability_never_income(self):
		invoice = self.invoice()
		entries = frappe.get_all(
			"GL Entry", {"voucher_no": invoice.name, "is_cancelled": 0}, ["account", "debit", "credit"]
		)
		credit = {e.account: e.credit for e in entries if e.credit}
		self.assertEqual(credit[self.accounts["deposit"]], DEPOSIT)
		self.assertEqual(credit[self.accounts["income"]], TUITION_FEE + EXAM_FEE)
		income_credit = sum(
			e.credit for e in entries if frappe.db.get_value("Account", e.account, "root_type") == "Income"
		)
		self.assertEqual(income_credit, TUITION_FEE + EXAM_FEE)  # the deposit is not in it


class FeeStructureLookupTests:
	def test_quota_and_category_specific_structures_win_over_generic(self):
		for code in ("FEE-GQ", "FEE-MQ", "FEE-NQ"):
			if not frappe.db.exists("Admission Quota", {"code": code}):
				frappe.get_doc({"doctype": "Admission Quota", "code": code, "title": code}).insert()
		quota = lambda code: frappe.db.get_value("Admission Quota", {"code": code})  # noqa: E731
		gq, mq, nq = quota("FEE-GQ"), quota("FEE-MQ"), quota("FEE-NQ")
		generic = self.structure.name
		by_quota = make_fee_structure(COLLEGE, PROGRAM, YEAR, {TUITION: 1}, self.accounts, oc_admission_quota=gq).name
		by_quota_category = make_fee_structure(
			COLLEGE, PROGRAM, YEAR, {TUITION: 2}, self.accounts, oc_admission_quota=gq, student_category=self.category()
		).name
		by_category = make_fee_structure(
			COLLEGE, PROGRAM, YEAR, {TUITION: 3}, self.accounts, student_category=self.category()
		).name
		lookup = lambda q, c: api.fee_structure_for(PROGRAM, YEAR, q, c, COLLEGE)  # noqa: E731
		self.assertEqual(lookup(gq, self.category()), by_quota_category)
		self.assertEqual(lookup(gq, None), by_quota)
		self.assertEqual(lookup(mq, self.category()), by_category)  # no MQ structure: category-specific fallback
		self.assertEqual(lookup(nq, None), generic)
		self.assertIsNone(api.fee_structure_for(PROGRAM, YEAR, gq, None, OTHER_COLLEGE))
		self.assertIsNone(api.fee_structure_for("No Such Program", YEAR, gq, None, COLLEGE))

	def category(self):
		if not frappe.db.exists("Student Category", "Fee Test Cat"):
			frappe.get_doc({"doctype": "Student Category", "category": "Fee Test Cat"}).insert()
		return "Fee Test Cat"


class FeeScheduleGenerationTests:
	def test_120_students_get_120_invoices_with_company_accounts_and_cost_centres(self):
		self.assertEqual(frappe.db.get_value("Fee Schedule", self.schedule.name, "status"), "Invoice Created")
		self.assertEqual(len(self.invoices), STUDENT_COUNT)
		self.assertEqual({i.student for i in self.invoices}, set(self.students))
		for name in [self.invoices[0].name, self.invoices[-1].name]:
			invoice = frappe.get_doc("Sales Invoice", name)
			self.assertEqual((invoice.company, invoice.docstatus, invoice.grand_total), (COLLEGE, 1, TUITION_FEE + EXAM_FEE + DEPOSIT))
			self.assertEqual(invoice.debit_to, "Debtors - FTC")
			accounts = {row.item_code: (row.income_account, row.cost_center) for row in invoice.items}
			self.assertEqual(accounts[TUITION], (self.accounts["income"], self.accounts["cost_center"]))
			self.assertEqual(accounts[CAUTION_DEPOSIT], (self.accounts["deposit"], self.accounts["cost_center"]))
		self.assertEqual(
			frappe.db.count("Sales Invoice", {"fee_schedule": self.schedule.name, "student": ("is", "set")}), STUDENT_COUNT
		)

	def test_every_invoice_has_a_unique_challan_number(self):
		numbers = {i.oc_challan_no for i in self.invoices}
		self.assertEqual(len(numbers), STUDENT_COUNT)
		self.assertTrue(all(n and n.startswith("CH-FTC-26-") for n in numbers))

	def test_challan_number_column_is_unique_in_the_database(self):
		other = self.invoices[1].name
		with self.assertRaises(Exception) as raised:
			frappe.db.set_value("Sales Invoice", other, "oc_challan_no", self.invoices[0].oc_challan_no)
		self.assertTrue(frappe.db.is_unique_key_violation(raised.exception))

	def test_challan_format_is_configurable(self):
		make_challan_format(COLLEGE, self.accounts["bank"], challan_prefix="CHL/{yyyy}/", challan_digits=4)
		first = self.make_invoice(self.students[0])
		second = self.make_invoice(self.students[1])
		year = today()[:4]
		self.assertEqual((first.oc_challan_no, second.oc_challan_no), (f"CHL/{year}/0001", f"CHL/{year}/0002"))

	def test_no_challan_format_means_no_challan_number(self):
		frappe.delete_doc("Challan Format", COLLEGE)
		self.assertFalse(self.make_invoice(self.students[0]).oc_challan_no)

	def test_unknown_placeholder_in_a_format_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_challan_format(COLLEGE, self.accounts["bank"], challan_prefix="CH-{nope}-")

	def test_bank_challan_print_shows_challan_and_bank_details(self):
		invoice = self.invoice()
		html = frappe.get_print("Sales Invoice", invoice.name, print_format="Bank Challan")
		for text in (invoice.oc_challan_no, "SBIN0000001", "30000000001", "State Bank of India", COLLEGE, invoice.student):
			self.assertIn(text, html)


class DailyFineRunTests:
	def run_fines(self, days_after_due):
		as_of = add_days(self.due, days_after_due)
		run = SimpleNamespace(get_parameters=lambda: {"as_of": as_of})
		sample = {i.name for i in self.invoices[:3]}  # fining all 120 invoices per step would take minutes
		items = [i for i in fines.fine_items(as_of) if i["invoice"] in sample]
		for item in items:
			fines.apply_fine(item, run)
		return items

	def fines_of(self, invoice):
		return frappe.get_all(
			"Fine Applied", {"sales_invoice": invoice.name}, ["slab_key", "amount", "fine_invoice"], order_by="amount"
		)

	def test_one_fine_per_slab_crossed_and_rerun_adds_nothing(self):
		invoice = self.invoice()
		self.assertEqual(self.run_fines(5), [])  # inside grace: nothing
		self.run_fines(6)  # day 1: first slab
		self.assertEqual([f.amount for f in self.fines_of(invoice)], [100])
		self.run_fines(20)  # day 15: second slab (1% of 47000), first not repeated
		self.assertEqual(sorted(f.amount for f in self.fines_of(invoice)), [100, 470])
		self.assertEqual(self.run_fines(20), [])  # re-run: nothing new
		self.run_fines(60)  # day 55: third slab
		self.assertEqual(sorted(f.amount for f in self.fines_of(invoice)), [100, 470, 500])
		self.assertEqual(self.run_fines(60), [])
		self.assertEqual(len(self.fines_of(invoice)), 3)

	def test_fine_invoices_are_submitted_for_the_student_and_company_in_the_fine_account(self):
		invoice = self.invoice()
		self.run_fines(6)
		fine = frappe.get_doc("Sales Invoice", self.fines_of(invoice)[0].fine_invoice)
		self.assertEqual((fine.docstatus, fine.company, fine.student, fine.customer), (1, COLLEGE, invoice.student, invoice.customer))
		self.assertEqual((fine.items[0].item_code, fine.grand_total), (FINE, 100))
		self.assertEqual(fine.items[0].income_account, self.accounts["income"])
		self.assertTrue(fine.oc_challan_no)  # payable at the bank like any fee

	def test_fine_invoices_are_never_fined_and_paid_invoices_are_skipped(self):
		self.run_fines(6)
		fine_invoices = frappe.get_all("Fine Applied", pluck="fine_invoice")
		self.assertEqual(len(fine_invoices), 3)
		paid = self.invoice(5)
		bank_import.make_payment_entry(
			{"company": COLLEGE, "reference": "PAID-1", "date": today(), "amount": paid.outstanding_amount}, paid
		)
		items = fines.fine_items(add_days(self.due, 90))  # the fine invoices are long overdue by now
		self.assertNotIn(paid.name, {i["invoice"] for i in items})
		self.assertFalse(set(fine_invoices) & {i["invoice"] for i in items})
		self.assertTrue(items)

	def test_category_rule_beats_the_all_fees_rule(self):
		tuition_rule = frappe.get_doc(
			{
				"doctype": "Fine Rule", "company": COLLEGE, "fee_category": TUITION, "grace_days": 0,
				"slabs": [{"from_day": 1, "to_day": 0, "amount": 7}],
			}
		).insert()
		items = fines.fine_items(add_days(self.due, 1))
		self.assertEqual({i["rule"] for i in items}, {tuition_rule.name})
		self.assertEqual(len(items), STUDENT_COUNT)

	def test_only_one_enabled_rule_per_company_and_fee(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Fine Rule", "company": COLLEGE, "slabs": [{"from_day": 1, "to_day": 0, "amount": 1}]}
			).insert()

	def test_invoice_without_student_or_company_rule_is_not_fined(self):
		frappe.db.set_value("Fine Rule", self.rule.name, "enabled", 0)
		self.assertEqual(fines.fine_items(add_days(self.due, 90)), [])

	def test_the_fine_table_refuses_a_second_fine_for_the_same_slab(self):
		self.run_fines(6)
		invoice = self.invoice()
		row = self.fines_of(invoice)[0]
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc(
				{
					"doctype": "Fine Applied", "sales_invoice": invoice.name, "slab_key": row.slab_key, "fine_rule": self.rule.name,
					"company": COLLEGE, "amount": 1,
				}
			).insert()

	def test_daily_run_queues_a_bulk_run_of_the_due_fines(self):
		with patch.object(fines, "run_bulk", return_value="BULK-1") as run_bulk:
			self.assertEqual(fines.daily_fine_run(add_days(self.due, 6)), "BULK-1")
		args, kwargs = run_bulk.call_args
		self.assertEqual(len(args[1]), STUDENT_COUNT)
		self.assertEqual((args[2], kwargs["parameters"]), (fines.HANDLER, {"as_of": add_days(self.due, 6)}))
		with patch.object(fines, "run_bulk") as run_bulk:
			self.assertIsNone(fines.daily_fine_run(add_days(self.due, 1)))  # within grace: nothing to queue
		run_bulk.assert_not_called()

	def test_bulk_runner_applies_fines_exactly_once_without_committing(self):
		items = fines.fine_items(add_days(self.due, 16))[:10]
		with patch.object(bulk, "enqueue_run"), patch.object(frappe.db, "commit"):  # keep the test transaction
			run = bulk.run_bulk(fines.RUN_TYPE, items, fines.HANDLER, key=fines.KEY, parameters={"as_of": add_days(self.due, 16)})
			bulk.process_bulk_run(run)
			again = bulk.run_bulk(fines.RUN_TYPE, items, fines.HANDLER, key=fines.KEY, parameters={"as_of": add_days(self.due, 16)})
			bulk.process_bulk_run(again)
		for name in (run, again):
			self.assertEqual(frappe.db.get_value("Bulk Run", name, "status"), "Completed")
		# 10 items = 5 invoices x 2 slabs; the second run found every (invoice, slab) done and added nothing.
		self.assertEqual(frappe.db.count("Fine Applied"), 10)
		self.assertEqual(frappe.db.count("Sales Invoice", {"remarks": ("like", "Late fine for%")}), 10)


def bank_csv(rows):
	out = io.StringIO()
	writer = csv.writer(out)
	writer.writerow(["challan_no", "amount", "date", "reference", "narration"])
	writer.writerows(rows)
	return out.getvalue().encode()


class BankCollectionImportTests:
	def file_rows(self, matched=48, unmatched=2, tag="A"):
		rows = [
			[self.invoices[n].oc_challan_no, TUITION_FEE + EXAM_FEE + DEPOSIT, today(), f"UTR-{tag}-{n:03d}", "x"]
			for n in range(matched)
		]
		rows += [[f"CH-NOPE-{n}", 1000, today(), f"UTR-{tag}-X{n}", "x"] for n in range(unmatched)]
		return rows

	def run_import(self, rows):
		doc = frappe.get_doc({"doctype": "Bank Collection Import", "company": COLLEGE, "collection_file": "/files/bank.csv"}).insert()
		with (
			patch.object(bank_import, "read_file", return_value=bank_csv(rows)),
			patch.object(bulk, "enqueue_run"),
			patch.object(frappe.db, "commit"),  # keep the test transaction; the runner's chunk commit is a no-op
		):
			run = bank_import.start_import(doc.name)
			bulk.process_bulk_run(run)
		return frappe.get_doc("Bank Collection Import", doc.name), run

	def test_50_row_file_matches_48_reports_2_and_reimport_adds_no_payments(self):
		rows = self.file_rows()
		self.assertEqual(len(rows), 50)
		first, run = self.run_import(rows)
		self.assertEqual(frappe.db.get_value("Bulk Run", run, "status"), "Completed")
		self.assertEqual((first.total_rows, first.matched_rows, first.unmatched_rows, first.duplicate_rows), (50, 48, 2, 0))
		self.assertEqual(first.status, "Completed with errors")
		unmatched = frappe.get_all(
			"Bank Collection Row", {"bank_collection_import": first.name, "status": "Unmatched"}, ["challan_no", "message"]
		)
		self.assertEqual(sorted(r.challan_no for r in unmatched), ["CH-NOPE-0", "CH-NOPE-1"])
		self.assertTrue(all(r.message for r in unmatched))
		payments = frappe.get_all("Payment Entry", {"reference_no": ("like", "UTR-A-%"), "docstatus": 1}, ["name", "paid_amount"])
		self.assertEqual(len(payments), 48)
		self.assertEqual({p.paid_amount for p in payments}, {TUITION_FEE + EXAM_FEE + DEPOSIT})
		self.assertEqual(self.invoice(0).outstanding_amount, 0)
		self.assertEqual(self.invoice(48).outstanding_amount, TUITION_FEE + EXAM_FEE + DEPOSIT)

		second, _run = self.run_import(rows)
		self.assertEqual((second.matched_rows, second.duplicate_rows, second.unmatched_rows), (0, 48, 2))
		self.assertEqual(
			frappe.db.count("Payment Entry", {"reference_no": ("like", "UTR-A-%"), "docstatus": 1}), 48
		)  # no duplicate Payment Entries

	def test_payment_entry_posts_to_the_challan_format_account(self):
		first, _run = self.run_import(self.file_rows(1, 0, "B"))
		row = frappe.get_doc("Bank Collection Row", {"bank_collection_import": first.name})
		payment = frappe.get_doc("Payment Entry", row.payment_entry)
		invoice = self.invoice(0)
		self.assertEqual((payment.company, payment.paid_to, payment.reference_no), (COLLEGE, self.accounts["bank"], "UTR-B-000"))
		self.assertEqual(
			(payment.references[0].reference_name, payment.references[0].allocated_amount), (invoice.name, invoice.grand_total)
		)
		self.assertEqual((row.status, row.sales_invoice), ("Matched", invoice.name))

	def test_overpayment_paid_invoice_and_bad_rows_are_reported_not_posted(self):
		rows = [
			[self.invoices[0].oc_challan_no, 10**7, today(), "UTR-C-1", ""],  # more than outstanding
			[self.invoices[1].oc_challan_no, "abc", today(), "UTR-C-2", ""],  # bad amount
			[self.invoices[1].oc_challan_no, 100, "not a date", "UTR-C-3", ""],  # bad date
			["", 100, today(), "UTR-C-4", ""],  # no challan
			[self.invoices[1].oc_challan_no, 100, today(), "", ""],  # no reference
		]
		result, _run = self.run_import(rows)
		self.assertEqual((result.matched_rows, result.unmatched_rows, result.invalid_rows), (0, 1, 4))
		self.assertEqual(frappe.db.count("Payment Entry", {"reference_no": ("like", "UTR-C-%")}), 0)

	def test_partial_collection_leaves_the_balance_and_a_second_reference_clears_it(self):
		number = self.invoices[0].oc_challan_no
		self.run_import([[number, 10000, today(), "UTR-D-1", ""]])
		self.assertEqual(self.invoice(0).outstanding_amount, TUITION_FEE + EXAM_FEE + DEPOSIT - 10000)
		self.run_import([[number, 10000, today(), "UTR-D-1", ""], [number, 37000, today(), "UTR-D-2", ""]])
		self.assertEqual(self.invoice(0).outstanding_amount, 0)

	def test_file_without_required_columns_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			bank_import.parse_rows(b"challan_no,amount\nA,1\n")

	def test_import_is_for_the_company_of_the_challan(self):
		doc = frappe.get_doc({"doctype": "Bank Collection Import", "company": OTHER_COLLEGE, "collection_file": "/files/x.csv"})
		doc.insert()
		item = {"import": doc.name, "company": OTHER_COLLEGE, "row_no": 1, "challan_no": self.invoices[0].oc_challan_no,
			"amount": "100", "date": today(), "reference": "UTR-E-1"}  # fmt: skip
		bank_import.process_row(item, None)
		self.assertEqual(frappe.db.get_value("Bank Collection Row", {"bank_collection_import": doc.name}, "status"), "Unmatched")


class FeeReceiptTests:
	def collect(self, reference="UTR-R-1", challan_format=None):
		invoice = self.invoice(0)
		item = {"company": COLLEGE, "reference": reference, "date": today(), "amount": invoice.outstanding_amount}
		return bank_import.make_payment_entry(item, invoice), invoice

	def test_receipt_numbers_follow_the_college_series_and_name_the_student(self):
		first, invoice = self.collect("UTR-R-1")
		second = bank_import.make_payment_entry(
			{"company": COLLEGE, "reference": "UTR-R-2", "date": today(), "amount": 100}, self.invoice(1)
		)
		year = today()[2:4]
		self.assertEqual((first.oc_receipt_no, second.oc_receipt_no), (f"FR-FTC-{year}-000001", f"FR-FTC-{year}-000002"))
		self.assertEqual((first.oc_student, second.oc_student), (invoice.student, self.invoice(1).student))

	def test_receipt_takes_the_college_letter_head(self):
		if not frappe.db.exists("Letter Head", "Fee Test LH"):
			frappe.get_doc({"doctype": "Letter Head", "letter_head_name": "Fee Test LH", "content": "<b>Fee Test College</b>"}).insert()
		make_challan_format(COLLEGE, self.accounts["bank"], letter_head="Fee Test LH")
		payment, _invoice = self.collect("UTR-R-3")
		self.assertEqual(payment.letter_head, "Fee Test LH")

	def test_receipt_print_shows_student_invoice_allocations_and_receipt_no(self):
		payment, invoice = self.collect("UTR-R-4")
		html = frappe.get_print("Payment Entry", payment.name, print_format="Fee Receipt")
		student_name = frappe.db.get_value("Student", invoice.student, "student_name")
		for text in (payment.oc_receipt_no, student_name, invoice.name, invoice.oc_challan_no, COLLEGE, "UTR-R-4"):
			self.assertIn(text, html)

	def test_a_payment_without_a_student_gets_no_receipt_number(self):
		customer = frappe.get_doc({"doctype": "Customer", "customer_name": "Fee Test Walk-in", "customer_group": "Student"}).insert()
		payment = frappe.get_doc(
			{
				"doctype": "Payment Entry", "payment_type": "Receive", "party_type": "Customer", "party": customer.name,
				"company": COLLEGE, "paid_from": "Debtors - FTC", "paid_to": self.accounts["bank"], "paid_amount": 10,
				"received_amount": 10, "reference_no": "UTR-W", "reference_date": today(),
			}
		).insert()
		payment.submit()
		self.assertFalse(payment.oc_receipt_no)


class TestCampusFinance(
	FeeHeadTests,
	FeeStructureLookupTests,
	FeeScheduleGenerationTests,
	DailyFineRunTests,
	BankCollectionImportTests,
	FeeReceiptTests,
	FinanceTestCase,
):
	"""All integration tests share one 120-student world: building it takes about a minute."""
