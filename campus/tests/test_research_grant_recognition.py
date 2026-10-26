"""P3-T16 (M08-05, blueprint D9) tests: grant income recognition, capital grants and interest on grant funds.

A Grant Income Recognition for a period posts one Journal Entry per run: for each sanction it debits the "Grant Received
in Advance" liability and credits grant income with the revenue spent, moves capital-head spending from the liability to
the Deferred Capital Grant, and releases the Deferred Capital Grant to grant income in line with the depreciation booked
on the sanction's cost centre. Each sanction is recognised once per period (sanction lock plus a unique key). Interest on
grant funds goes to the liability unless the agency or college treats it as income."""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import add_days, today

from campus.research.budget_control import BUDGET_HEAD_FIELD
from campus.research.grant_recognition import recognition_amounts
from campus.tests.finance_factories import make_account
from campus.tests.research_fixtures import ABBR, COLLEGE, SanctionFixtures


class TestRecognitionAmounts(UnitTestCase):
	"""Cumulative to the period end: what was spent / depreciated against what was already recognised."""

	def amounts(self, spent=(0, 0, 0), done=(0, 0, 0)):
		return recognition_amounts(
			frappe._dict(zip(("revenue", "capital", "depreciation"), spent, strict=True)),
			frappe._dict(zip(("revenue", "capital", "released"), done, strict=True)),
		)

	def test_first_period_recognises_everything_spent(self):
		self.assertEqual(
			self.amounts(spent=(45000, 300000, 5000)), {"revenue": 45000, "capital": 300000, "release": 5000}
		)

	def test_only_the_new_spending_is_recognised(self):
		result = self.amounts(spent=(70000, 300000, 8000), done=(45000, 300000, 5000))
		self.assertEqual(result, {"revenue": 25000, "capital": 0, "release": 3000})

	def test_nothing_new_gives_zero(self):
		self.assertEqual(
			self.amounts(spent=(45000, 300000, 5000), done=(45000, 300000, 5000)),
			{"revenue": 0, "capital": 0, "release": 0},
		)

	def test_a_credit_note_reverses_recognised_income(self):
		self.assertEqual(self.amounts(spent=(40000, 0, 0), done=(45000, 0, 0))["revenue"], -5000)

	def test_release_never_passes_what_was_capitalised(self):
		# the asset depreciates beyond the grant share: release stops at the capitalised grant
		self.assertEqual(self.amounts(spent=(0, 10000, 12000), done=(0, 10000, 9000))["release"], 1000)
		self.assertEqual(self.amounts(spent=(0, 10000, 15000), done=(0, 10000, 10000))["release"], 0)

	def test_release_follows_a_reversed_depreciation(self):
		self.assertEqual(self.amounts(spent=(0, 10000, 4000), done=(0, 10000, 5000))["release"], -1000)

	def test_amounts_are_rounded_to_the_currency(self):
		self.assertEqual(self.amounts(spent=(100.004, 0, 0))["revenue"], 100.0)


class TestGrantRecognition(SanctionFixtures):
	def setUp(self):
		super().setUp()
		self.equipment_account = f"Capital Equipment - {ABBR}"
		self.depreciation_account = f"Depreciation - {ABBR}"
		self.accumulated_account = f"Accumulated Depreciation - {ABBR}"
		self.income = self.settings.grant_income_account
		self.deferred = self.settings.deferred_capital_grant_account

	def submitted_sanction(self, **values):
		sanction = self.sanction(**values)
		sanction.submit()
		return sanction.reload()

	# vouchers
	def spend(self, sanction, account, amount, head, posting_date=None):
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": COLLEGE,
				"posting_date": posting_date or today(),
				"accounts": [
					{
						"account": account,
						"debit_in_account_currency": amount,
						"cost_center": sanction.cost_center,
						"project": sanction.project,
						BUDGET_HEAD_FIELD: head,
					},
					{
						"account": self.bank,
						"credit_in_account_currency": amount,
						"cost_center": sanction.cost_center,
					},
				],
			}  # fmt: skip
		).insert()
		entry.submit()
		return entry

	def depreciate(self, sanction, amount):
		"""What ERPNext's depreciation entry posts for an asset whose cost centre is the sanction's."""
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": COLLEGE,
				"posting_date": today(),
				"voucher_type": "Depreciation Entry",
				"accounts": [
					{
						"account": self.depreciation_account,
						"debit_in_account_currency": amount,
						"cost_center": sanction.cost_center,
					},
					{
						"account": self.accumulated_account,
						"credit_in_account_currency": amount,
						"cost_center": sanction.cost_center,
					},
				],
			}  # fmt: skip
		).insert()
		entry.submit()

	def interest(self, sanction, amount, **values):
		doc = frappe.get_doc(
			{
				"doctype": "Grant Interest",
				"sanction": sanction.name,
				"posting_date": today(),
				"amount": amount,
				"received_in": self.bank,
				"reference_no": "INT0001",
				**values,
			}  # fmt: skip
		).insert()
		doc.submit()
		return doc

	def recognition(self, sanctions=None, from_date=None, to_date=None, submit=True):
		doc = frappe.get_doc(
			{
				"doctype": "Grant Income Recognition",
				"company": COLLEGE,
				"from_date": from_date or self.year1.start,
				"to_date": to_date or today(),
				"sanctions": [{"sanction": s.name} for s in sanctions or []],
			}  # fmt: skip
		).insert()
		if submit:
			doc.submit()
		return doc

	def balance(self, account, sanction):
		"""Credit balance of `account` on the sanction's cost centre."""
		row = frappe.db.sql(
			"""select coalesce(sum(credit - debit), 0) from `tabGL Entry`
			where account = %s and cost_center = %s and is_cancelled = 0""",
			(account, sanction.cost_center),
		)
		return row[0][0]

	def gl_count(self, sanction):
		return frappe.db.count("GL Entry", {"cost_center": sanction.cost_center, "is_cancelled": 0})

	def funded(self, sanction):
		"""The fixture: 510,000 received, 1,000 interest, 45,000 revenue spent, a 300,000 asset depreciated by 5,000."""
		self.receipt(sanction).submit()
		self.interest(sanction, 1000)
		self.spend(sanction, self.consumables_account, 40000, self.consumables)
		self.spend(sanction, self.travel_account, 5000, self.travel)
		self.spend(sanction, self.equipment_account, 300000, self.equipment)
		self.depreciate(sanction, 5000)

	# acceptance 1: liability reconciliation
	def test_liability_reconciles_per_sanction(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		doc = self.recognition([sanction])
		[row] = doc.sanctions
		self.assertEqual((row.revenue_amount, row.capital_amount, row.release_amount), (45000, 300000, 5000))
		# receipts + interest (liability) - expenditure recognised - capitalised grants
		self.assertEqual(self.balance(sanction.liability_account, sanction), 510000 + 1000 - 45000 - 300000)
		self.assertEqual(self.balance(self.deferred, sanction), 300000 - 5000)
		self.assertEqual(self.balance(self.income, sanction), 45000 + 5000)

	def test_one_journal_entry_with_the_sanction_project_on_every_row(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		doc = self.recognition([sanction])
		entry = frappe.get_doc("Journal Entry", doc.journal_entry)
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual(str(entry.posting_date), str(doc.to_date))
		self.assertEqual(
			{(r.cost_center, r.project) for r in entry.accounts}, {(sanction.cost_center, sanction.project)}
		)
		self.assertEqual(
			{r.account for r in entry.accounts}, {sanction.liability_account, self.income, self.deferred}
		)

	def test_sanctions_default_to_the_colleges_submitted_ones(self):
		sanction = self.submitted_sanction()
		self.sanction()  # a draft is not recognised
		self.receipt(sanction).submit()
		self.spend(sanction, self.consumables_account, 1000, self.consumables)
		doc = self.recognition()
		self.assertIn(sanction.name, [row.sanction for row in doc.sanctions])
		self.assertEqual(self.balance(self.income, sanction), 1000)

	def test_a_draft_or_repeated_sanction_is_refused(self):
		draft = self.sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "submitted"):
			self.recognition([draft], submit=False)
		sanction = self.submitted_sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "more than once"):
			self.recognition([sanction, sanction], submit=False)

	def test_spending_after_the_period_waits_for_its_period(self):
		sanction = self.submitted_sanction()
		self.receipt(sanction).submit()
		self.spend(sanction, self.consumables_account, 1000, self.consumables)
		self.spend(
			sanction, self.consumables_account, 700, self.consumables, posting_date=add_days(today(), 1)
		)
		self.recognition([sanction])
		self.assertEqual(self.balance(self.income, sanction), 1000)
		self.recognition([sanction], from_date=add_days(today(), 1), to_date=add_days(today(), 1))
		self.assertEqual(self.balance(self.income, sanction), 1700)

	def test_a_credit_note_in_a_later_period_reverses_income_with_flipped_rows(self):
		sanction = self.submitted_sanction()
		self.receipt(sanction).submit()
		self.spend(
			sanction, self.consumables_account, 4000, self.consumables, posting_date=add_days(today(), -2)
		)
		self.recognition([sanction], to_date=add_days(today(), -1))
		credit = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": COLLEGE,
				"posting_date": today(),
				"accounts": [
					{
						"account": self.consumables_account,
						"credit_in_account_currency": 1500,
						"cost_center": sanction.cost_center,
						"project": sanction.project,
						BUDGET_HEAD_FIELD: self.consumables,
					},
					{
						"account": self.bank,
						"debit_in_account_currency": 1500,
						"cost_center": sanction.cost_center,
					},
				],
			}  # fmt: skip
		).insert()
		credit.submit()  # e.g. a supplier's credit note for returned consumables
		doc = self.recognition([sanction], from_date=today(), to_date=today())
		self.assertEqual(doc.sanctions[0].revenue_amount, -1500)
		rows = {
			(r.account, r.debit, r.credit)
			for r in frappe.get_doc("Journal Entry", doc.journal_entry).accounts
		}
		self.assertEqual(rows, {(self.income, 1500, 0), (sanction.liability_account, 0, 1500)})
		self.assertEqual(self.balance(self.income, sanction), 2500)
		self.assertEqual(self.balance(sanction.liability_account, sanction), 510000 - 2500)

	# acceptance 2: idempotent per period
	def test_running_twice_for_the_same_period_posts_nothing_new(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		self.recognition([sanction])
		before = self.gl_count(sanction)
		with self.assertRaisesRegex(frappe.ValidationError, "Nothing to recognise"):
			self.recognition([sanction])
		with self.assertRaisesRegex(frappe.ValidationError, "Nothing to recognise"):
			self.recognition([sanction], from_date=today())  # same period end, other start
		self.assertEqual(self.gl_count(sanction), before)
		self.assertEqual(self.balance(self.income, sanction), 50000)

	def test_a_period_already_recognised_is_skipped_even_with_new_spending(self):
		sanction = self.submitted_sanction()
		self.receipt(sanction).submit()
		self.spend(sanction, self.consumables_account, 1000, self.consumables)
		self.recognition([sanction])
		self.spend(
			sanction, self.consumables_account, 300, self.consumables
		)  # back-dated into the recognised period
		with self.assertRaisesRegex(frappe.ValidationError, "Nothing to recognise"):
			self.recognition([sanction])
		self.recognition([sanction], from_date=add_days(today(), 1), to_date=add_days(today(), 1))
		self.assertEqual(self.balance(self.income, sanction), 1300)  # caught up in the next period

	def test_recognition_key_is_unique_per_sanction_and_period(self):
		field = frappe.get_meta("Grant Income Recognition Sanction").get_field("recognition_key")
		self.assertTrue(field.unique)
		sanction = self.submitted_sanction()
		self.receipt(sanction).submit()
		self.spend(sanction, self.consumables_account, 1000, self.consumables)
		doc = self.recognition([sanction])
		self.assertEqual(doc.sanctions[0].recognition_key, f"{sanction.name}|{doc.to_date}")
		duplicate = frappe.get_doc(
			{"doctype": "Grant Income Recognition Sanction", "parent": "GIR-X", "parenttype": "Grant Income Recognition",
			 "parentfield": "sanctions", "sanction": sanction.name, "recognition_key": doc.sanctions[0].recognition_key}
		)  # fmt: skip
		with self.assertRaises(frappe.UniqueValidationError):
			duplicate.db_insert()

	def test_submit_locks_the_sanction(self):
		sanction = self.submitted_sanction()
		self.receipt(sanction).submit()
		self.spend(sanction, self.consumables_account, 1000, self.consumables)
		doc = self.recognition([sanction], submit=False)
		locked = []
		get_value = frappe.db.get_value

		def spy(doctype, *args, **kwargs):
			if doctype == "Sanction" and kwargs.get("for_update"):
				locked.append(args[0])
			return get_value(doctype, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=spy):
			doc.submit()
		self.assertIn(sanction.name, locked)

	# acceptance 3: a fully spent revenue grant nets to zero
	def test_fully_spent_revenue_grant_nets_to_zero(self):
		sanction = self.submitted_sanction(
			heads=[(self.consumables, self.year1.name, 1000)], instalments=[("First", 1000)]
		)
		self.receipt(sanction).submit()
		self.spend(sanction, self.consumables_account, 1000, self.consumables)
		self.recognition([sanction])
		profit = frappe.db.sql(
			"""select coalesce(sum(gl.credit - gl.debit), 0) from `tabGL Entry` gl
			join `tabAccount` a on a.name = gl.account
			where gl.cost_center = %s and gl.is_cancelled = 0 and a.root_type in ('Income', 'Expense')""",
			sanction.cost_center,
		)[0][0]
		self.assertEqual(profit, 0)
		self.assertEqual(self.balance(self.income, sanction), 1000)
		self.assertEqual(self.balance(sanction.liability_account, sanction), 0)

	# cancel
	def test_cancel_reverses_and_frees_the_period(self):
		sanction = self.submitted_sanction()
		self.funded(sanction)
		doc = self.recognition([sanction])
		doc.cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", doc.journal_entry, "docstatus"), 2)
		self.assertEqual(self.balance(sanction.liability_account, sanction), 511000)
		self.assertIsNone(
			frappe.db.get_value("Grant Income Recognition Sanction", doc.sanctions[0].name, "recognition_key")
		)
		self.recognition([sanction])  # the period can be recognised again
		self.assertEqual(self.balance(sanction.liability_account, sanction), 166000)

	def test_only_the_latest_recognition_of_a_sanction_can_be_cancelled(self):
		sanction = self.submitted_sanction()
		self.receipt(sanction).submit()
		self.spend(sanction, self.consumables_account, 1000, self.consumables)
		first = self.recognition([sanction])
		self.spend(
			sanction, self.consumables_account, 500, self.consumables, posting_date=add_days(today(), 1)
		)
		self.recognition([sanction], from_date=add_days(today(), 1), to_date=add_days(today(), 1))
		with self.assertRaisesRegex(frappe.ValidationError, "later"):
			first.cancel()

	def test_sanction_with_a_recognition_cannot_be_cancelled(self):
		sanction = self.submitted_sanction()
		self.receipt(sanction).submit()
		self.spend(sanction, self.consumables_account, 1000, self.consumables)
		self.recognition([sanction])
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Sanction", sanction.name).cancel()

	# interest on grant funds
	def test_interest_goes_to_the_liability_by_default(self):
		sanction = self.submitted_sanction()
		doc = self.interest(sanction, 1000)
		self.assertEqual(
			(doc.interest_treatment, doc.credited_to), ("Grant Liability", sanction.liability_account)
		)
		self.assertEqual(self.balance(sanction.liability_account, sanction), 1000)
		doc.cancel()
		self.assertEqual(self.balance(sanction.liability_account, sanction), 0)

	def test_interest_treated_as_income_is_kept_out_of_the_liability(self):
		interest_income = make_account(COLLEGE, ABBR, "RSA Interest Income", "Indirect Income")
		frappe.db.set_value(
			"Research Settings",
			COLLEGE,
			{"interest_treatment": "Interest Income", "interest_income_account": interest_income},
		)
		frappe.clear_document_cache("Research Settings", COLLEGE)
		self.addCleanup(
			frappe.clear_document_cache, "Research Settings", COLLEGE
		)  # the rollback restores the row, not the cache
		sanction = self.submitted_sanction()
		self.receipt(sanction).submit()
		doc = self.interest(sanction, 1000)
		self.assertEqual(doc.credited_to, interest_income)
		self.spend(sanction, self.consumables_account, 2000, self.consumables)
		self.recognition([sanction])
		self.assertEqual(self.balance(sanction.liability_account, sanction), 510000 - 2000)
		self.assertEqual(self.balance(interest_income, sanction), 1000)

	def test_interest_needs_a_submitted_sanction_and_a_bank_account(self):
		draft = self.sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "submitted"):
			self.interest(draft, 100)
		sanction = self.submitted_sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "bank or cash"):
			self.interest(sanction, 100, received_in=self.consumables_account)
