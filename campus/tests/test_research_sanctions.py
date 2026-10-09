"""P3-T14 (M08-03, M08-05) tests: Sanction, project set-up and Grant Receipts. Submitting a sanction creates one
ERPNext Project, one Cost Center under the college's research cost centre, one Budget per revenue head account (Stop or
Warn per the scheme, distributed by the per-year sanctioned amounts) and the liability account "Grant Received in
Advance - <sanction>"; cancelling before any transaction removes them. A Grant Receipt posts a Journal Entry crediting
that liability (blueprint D9), never income. Seed money from the "Institution" agency works the same way."""

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe.utils import add_days, getdate, today

from campus.research.setup import INSTITUTION_AGENCY, setup_research
from campus.tests.finance_factories import ensure_fiscal_years, make_account, make_company_with_accounts
from campus.tests.utils import CampusTestCase

COLLEGE, ABBR = "Research Sanction Test College", "RSAT"
OTHER, OTHER_ABBR = "Research Sanction Other College", "RSAO"


class TestSanction(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_fiscal_years()
		make_company_with_accounts(COLLEGE, ABBR)
		make_company_with_accounts(OTHER, OTHER_ABBR)
		if not frappe.db.exists("Gender", "Male"):
			frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()

	def setUp(self):
		frappe.db.savepoint("research_sanction_test")
		self.addCleanup(frappe.db.rollback, save_point="research_sanction_test")
		setup_research()
		self.year1 = frappe._dict(zip(("name", "start", "end"), get_fiscal_year(today(), company=COLLEGE)[:3], strict=True))
		next_year = get_fiscal_year(add_days(self.year1.end, 1), company=COLLEGE)
		self.year2 = frappe._dict(zip(("name", "start", "end"), next_year[:3], strict=True))
		self.research_cc = self.make_group_cost_center(COLLEGE, ABBR, "Research Projects")
		self.settings = self.make_settings(COLLEGE, ABBR, self.research_cc)
		self.consumables_account = make_account(COLLEGE, ABBR, "RSA Consumables", "Indirect Expenses")
		self.travel_account = make_account(COLLEGE, ABBR, "RSA Travel", "Indirect Expenses")
		self.consumables = self.make_head("RSA Consumables", [(COLLEGE, self.consumables_account)])
		self.travel = self.make_head("RSA Travel", [(COLLEGE, self.travel_account)])
		self.equipment = self.make_head("RSA Equipment", [(COLLEGE, f"Capital Equipment - {ABBR}")], is_capital=1)
		self.bank = make_account(COLLEGE, ABBR, "RSA Grant Bank", "Bank Accounts", account_type="Bank", root_type="Asset")
		self.agency = frappe.get_doc({"doctype": "Funding Agency", "agency_name": "RSA Science Board"}).insert().name
		self.scheme = self.make_scheme("RSA Core Grant", [self.consumables, self.travel, self.equipment])
		self.pi = self.make_employee("Pi", COLLEGE)
		self.co_pi = self.make_employee("CoPi", COLLEGE)

	# fixtures
	def make_group_cost_center(self, company, abbr, name):
		root = frappe.db.get_value("Cost Center", {"company": company, "is_group": 1, "parent_cost_center": ["is", "not set"]})
		full = f"{name} - {abbr}"
		if not frappe.db.exists("Cost Center", full):
			frappe.get_doc(
				{"doctype": "Cost Center", "cost_center_name": name, "company": company, "parent_cost_center": root, "is_group": 1}
			).insert()  # fmt: skip
		return full

	def make_settings(self, company, abbr, research_cc=None):
		return frappe.get_doc(
			{
				"doctype": "Research Settings", "company": company, "research_cost_center": research_cc,
				"grant_liability_parent": f"Current Liabilities - {abbr}",
				"grant_income_account": make_account(company, abbr, "Grant Income", "Indirect Income"),
				"deferred_capital_grant_account": make_account(company, abbr, "Deferred Capital Grant", "Non-Current Liabilities"),
			}  # fmt: skip
		).insert()

	def make_head(self, name, accounts, is_capital=0):
		return frappe.get_doc(
			{"doctype": "Grant Budget Head", "head_name": name, "is_capital": is_capital,
			 "accounts": [{"company": c, "account": a} for c, a in accounts]}
		).insert().name  # fmt: skip

	def make_scheme(self, name, heads, agency=None, budget_action="Stop"):
		return frappe.get_doc(
			{"doctype": "Funding Scheme", "scheme_name": name, "funding_agency": agency or self.agency,
			 "budget_action": budget_action, "heads": [{"budget_head": h} for h in heads]}
		).insert().name  # fmt: skip

	def make_employee(self, first_name, company):
		return frappe.get_doc(
			{
				"doctype": "Employee", "first_name": first_name, "last_name": frappe.generate_hash(length=6), "gender": "Male",
				"date_of_birth": "1980-01-01", "date_of_joining": "2010-01-01", "company": company,
				"personal_email": f"{first_name.lower()}-{frappe.generate_hash(length=6)}@example.com",
			}  # fmt: skip
		).insert().name

	def heads(self):
		y1, y2 = self.year1.name, self.year2.name
		return [
			(self.consumables, y1, 200000), (self.consumables, y2, 100000),
			(self.travel, y1, 30000), (self.travel, y2, 20000),
			(self.equipment, y1, 500000),
		]  # fmt: skip

	def sanction(self, heads=None, instalments=None, scheme=None, agency=None, company=COLLEGE, **values):
		heads = heads or self.heads()
		total = sum(amount for _head, _year, amount in heads)
		instalments = instalments or [("First", total * 0.6), ("Second", total * 0.4)]
		return frappe.get_doc(
			{
				"doctype": "Sanction", "title": "Low-cost water sensors", "company": company,
				"sanction_order_no": f"DST/RSA/{frappe.generate_hash(length=6)}", "sanction_order_date": self.year1.start,
				"funding_agency": agency or self.agency, "funding_scheme": scheme or self.scheme,
				"principal_investigator": self.pi, "co_investigators": [{"employee": self.co_pi}],
				"start_date": self.year1.start, "end_date": self.year2.end,
				"heads": [{"budget_head": h, "fiscal_year": y, "amount": a} for h, y, a in heads],
				"instalments": [{"instalment": label, "amount": amount, "due_date": self.year1.start} for label, amount in instalments],
				"conditions": "Equipment to be procured in year 1.", **values,
			}  # fmt: skip
		).insert()

	def receipt(self, sanction, instalment="First", amount=None, **values):
		amount = amount or next(row.amount for row in sanction.instalments if row.instalment == instalment)
		return frappe.get_doc(
			{
				"doctype": "Grant Receipt", "sanction": sanction.name, "instalment": instalment, "amount": amount,
				"posting_date": today(), "received_in": self.bank, "reference_no": "UTR0001", "reference_date": today(),
				**values,
			}  # fmt: skip
		).insert()

	def budgets(self, cost_center):
		return frappe.get_all(
			"Budget",
			{"cost_center": cost_center, "docstatus": 1},
			["name", "account", "budget_amount", "action_if_annual_budget_exceeded",
			 "action_if_accumulated_monthly_budget_exceeded", "from_fiscal_year", "to_fiscal_year"],
		)  # fmt: skip

	# set-up validation
	def test_scheme_must_be_usable_by_the_college(self):
		other_head = self.make_head("RSA Unmapped", [(OTHER, make_account(OTHER, OTHER_ABBR, "RSA Other", "Indirect Expenses"))])
		scheme = self.make_scheme("RSA Unusable", [self.consumables, other_head])
		with self.assertRaisesRegex(frappe.ValidationError, "no account mapped"):
			self.sanction(heads=[(self.consumables, self.year1.name, 1000)], scheme=scheme)

	def test_scheme_must_belong_to_the_agency(self):
		other_agency = frappe.get_doc({"doctype": "Funding Agency", "agency_name": "RSA Other Board"}).insert().name
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Other Board"):
			self.sanction(agency=other_agency)

	def test_heads_come_from_the_scheme_once_per_year_inside_the_period(self):
		outside = self.make_head("RSA Outside", [(COLLEGE, self.consumables_account)])
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Outside"):
			self.sanction(heads=[(outside, self.year1.name, 1000)])
		with self.assertRaisesRegex(frappe.ValidationError, "more than once"):
			self.sanction(heads=[(self.consumables, self.year1.name, 1000), (self.consumables, self.year1.name, 500)])
		later = get_fiscal_year(add_days(self.year2.end, 1), company=COLLEGE)[0]
		with self.assertRaisesRegex(frappe.ValidationError, "outside the sanction period"):
			self.sanction(heads=[(self.consumables, later, 1000)])
		with self.assertRaisesRegex(frappe.ValidationError, "amount"):
			self.sanction(heads=[(self.consumables, self.year1.name, 0)])

	def test_instalments_must_add_up_to_the_sanctioned_total(self):
		with self.assertRaisesRegex(frappe.ValidationError, "add up"):
			self.sanction(instalments=[("First", 1000)])
		with self.assertRaisesRegex(frappe.ValidationError, "more than once"):
			self.sanction(instalments=[("First", 425000), ("First", 425000)])

	def test_revenue_head_must_map_to_one_account(self):
		second = make_account(COLLEGE, ABBR, "RSA Chemicals", "Indirect Expenses")
		head = frappe.get_doc("Grant Budget Head", self.consumables)
		head.append("accounts", {"company": COLLEGE, "account": second})
		head.save()
		with self.assertRaisesRegex(frappe.ValidationError, "one account"):
			self.sanction()

	def test_research_cost_centre_needed_to_submit(self):
		frappe.db.set_value("Research Settings", COLLEGE, "research_cost_center", None)
		frappe.clear_document_cache("Research Settings", COLLEGE)
		sanction = self.sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "Research Cost Centre"):
			sanction.submit()

	def test_research_cost_centre_must_be_a_group_of_the_college(self):
		settings = frappe.get_doc("Research Settings", COLLEGE)
		settings.research_cost_center = frappe.db.get_value("Cost Center", {"company": COLLEGE, "is_group": 0})
		with self.assertRaisesRegex(frappe.ValidationError, "group"):
			settings.save()
		settings.research_cost_center = self.make_group_cost_center(OTHER, OTHER_ABBR, "Research Projects")
		with self.assertRaisesRegex(frappe.ValidationError, COLLEGE):
			settings.save()

	def test_totals_from_heads(self):
		sanction = self.sanction()
		self.assertEqual(sanction.total_sanctioned, 850000)
		self.assertEqual(sanction.currency, frappe.get_cached_value("Company", COLLEGE, "default_currency"))

	# acceptance 1: one Project, Cost Center and Budget set; cancel removes them
	def test_submit_creates_one_project_cost_center_budget_set_and_liability(self):
		sanction = self.sanction()
		sanction.submit()
		sanction.reload()

		project = frappe.get_doc("Project", sanction.project)
		self.assertEqual((project.company, project.cost_center), (COLLEGE, sanction.cost_center))
		self.assertEqual(getdate(project.expected_end_date), getdate(self.year2.end))
		cost_center = frappe.db.get_value("Cost Center", sanction.cost_center, ["parent_cost_center", "is_group", "company"], as_dict=True)
		self.assertEqual((cost_center.parent_cost_center, cost_center.is_group, cost_center.company), (self.research_cc, 0, COLLEGE))
		liability = frappe.db.get_value(
			"Account", sanction.liability_account, ["account_name", "parent_account", "root_type", "is_group"], as_dict=True
		)
		self.assertEqual(liability.account_name, f"Grant Received in Advance - {sanction.name}")
		self.assertEqual((liability.parent_account, liability.root_type, liability.is_group), (f"Current Liabilities - {ABBR}", "Liability", 0))

		budgets = {row.account: row for row in self.budgets(sanction.cost_center)}
		self.assertEqual(set(budgets), {self.consumables_account, self.travel_account})  # capital heads: no ERPNext budget
		self.assertEqual(budgets[self.consumables_account].budget_amount, 300000)
		self.assertEqual(budgets[self.travel_account].budget_amount, 50000)
		for row in budgets.values():
			self.assertEqual((row.from_fiscal_year, row.to_fiscal_year), (self.year1.name, self.year2.name))
			self.assertEqual(row.action_if_annual_budget_exceeded, "Stop")
			self.assertEqual(row.action_if_accumulated_monthly_budget_exceeded, "Stop")
		distribution = frappe.get_all(
			"Budget Distribution", {"parent": budgets[self.consumables_account].name}, ["start_date", "amount"], order_by="start_date"
		)
		self.assertEqual([(getdate(d.start_date), d.amount) for d in distribution], [(getdate(self.year1.start), 200000), (getdate(self.year2.start), 100000)])

		self.assertEqual(frappe.db.count("Project", {"name": sanction.project}), 1)
		self.assertEqual(frappe.db.count("Cost Center", {"parent_cost_center": self.research_cc}), 1)

	def test_budget_stops_spending_beyond_the_year_sanctioned_to_date(self):
		from erpnext.accounts.doctype.budget.budget import BudgetError

		sanction = self.sanction()
		sanction.submit()
		sanction.reload()

		def spend(amount):
			entry = frappe.get_doc(
				{
					"doctype": "Journal Entry", "company": COLLEGE, "posting_date": today(),
					"accounts": [
						{"account": self.consumables_account, "debit_in_account_currency": amount, "cost_center": sanction.cost_center},
						{"account": self.bank, "credit_in_account_currency": amount, "cost_center": sanction.cost_center},
					],
				}  # fmt: skip
			).insert()
			entry.submit()

		spend(150000)
		with self.assertRaises(BudgetError):  # year 1 has 200000 of the head's 300000
			spend(60000)

	def test_warn_scheme_gives_warn_budgets(self):
		scheme = self.make_scheme("RSA Warn Grant", [self.consumables], budget_action="Warn")
		sanction = self.sanction(heads=[(self.consumables, self.year1.name, 1000)], instalments=[("First", 1000)], scheme=scheme)
		sanction.submit()
		[budget] = self.budgets(sanction.reload().cost_center)
		self.assertEqual(budget.action_if_annual_budget_exceeded, "Warn")

	def test_cancel_before_any_transaction_removes_the_set_up(self):
		sanction = self.sanction()
		sanction.submit()
		sanction.reload()
		project, cost_center, liability = sanction.project, sanction.cost_center, sanction.liability_account
		budgets = [row.name for row in self.budgets(cost_center)]
		sanction.cancel()
		self.assertFalse(frappe.db.exists("Project", project))
		self.assertFalse(frappe.db.exists("Cost Center", cost_center))
		self.assertFalse(frappe.db.exists("Account", liability))
		self.assertFalse(frappe.db.exists("Budget", {"name": ["in", budgets]}))

	def test_cancel_refused_once_money_was_received(self):
		sanction = self.sanction()
		sanction.submit()
		receipt = self.receipt(sanction.reload())
		receipt.submit()
		self.assert_cancel_refused(sanction.name)
		receipt.reload().cancel()
		self.assert_cancel_refused(sanction.name)
		self.assertTrue(frappe.db.exists("Project", sanction.reload().project))
		self.assertEqual(sanction.docstatus, 1)

	def test_cancel_amend_submit_gives_one_set_up(self):
		sanction = self.sanction()
		sanction.submit()
		sanction.cancel()
		amended = frappe.copy_doc(sanction)
		amended.amended_from, amended.docstatus = sanction.name, 0
		amended.insert()
		amended.submit()
		amended.reload()
		self.assertEqual(frappe.get_all("Cost Center", {"parent_cost_center": self.research_cc}, pluck="name"), [amended.cost_center])
		self.assertEqual(frappe.get_all("Project", {"company": COLLEGE}, pluck="name"), [amended.project])
		self.assertEqual(len(self.budgets(amended.cost_center)), 2)

	def test_cancel_refused_while_another_document_uses_the_set_up(self):
		sanction = self.sanction()
		sanction.submit()
		sanction.reload()
		frappe.get_doc(
			{
				"doctype": "Journal Entry", "company": COLLEGE, "posting_date": today(),
				"accounts": [
					{"account": self.consumables_account, "debit_in_account_currency": 10, "cost_center": sanction.cost_center,
					 "project": sanction.project, "oc_budget_head": self.consumables},
					{"account": self.bank, "credit_in_account_currency": 10},
				],
			}  # fmt: skip
		).insert()  # a draft
		frappe.db.savepoint("sanction_cancel")
		with self.assertRaisesRegex(frappe.ValidationError, "used by other documents") as raised:
			frappe.get_doc("Sanction", sanction.name).cancel()
		self.assertNotIsInstance(raised.exception, frappe.LinkExistsError)
		frappe.db.rollback(save_point="sanction_cancel")

	def test_cancel_checks_postings_with_locking_reads(self):
		from unittest.mock import patch

		sanction = self.sanction()
		sanction.submit()
		real, locked = frappe.db.get_value, []

		def spy(doctype, *args, **kwargs):
			if doctype == "GL Entry" and kwargs.get("for_update"):
				locked.append(args)
			return real(doctype, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=spy):
			frappe.get_doc("Sanction", sanction.name).cancel()
		self.assertEqual(len(locked), 3)  # liability account, cost centre, project

	def assert_cancel_refused(self, name):
		frappe.db.savepoint("sanction_cancel")  # a failed request rolls back; so does this
		with self.assertRaisesRegex(frappe.ValidationError, "accounting entries"):
			frappe.get_doc("Sanction", name).cancel()
		frappe.db.rollback(save_point="sanction_cancel")

	# acceptance 2: a receipt credits the sanction's liability, never income
	def gl(self, voucher):
		return frappe.get_all(
			"GL Entry", {"voucher_no": voucher, "is_cancelled": 0}, ["account", "debit", "credit", "project", "cost_center"]
		)

	def test_receipt_credits_the_liability_never_income(self):
		sanction = self.sanction()
		sanction.submit()
		sanction.reload()
		receipt = self.receipt(sanction)
		receipt.submit()
		receipt.reload()

		entries = self.gl(receipt.journal_entry)
		credits = [e for e in entries if e.credit]
		self.assertEqual([(e.account, e.credit, e.project, e.cost_center) for e in credits],
			[(sanction.liability_account, 510000, sanction.project, sanction.cost_center)])  # fmt: skip
		self.assertEqual([(e.account, e.debit) for e in entries if e.debit], [(self.bank, 510000)])
		income = frappe.get_all("Account", {"company": COLLEGE, "root_type": "Income"}, pluck="name")
		self.assertFalse([e for e in entries if e.account in income])

		sanction.reload()
		self.assertEqual(sanction.total_received, 510000)
		self.assertEqual({row.instalment: row.received_amount for row in sanction.instalments}, {"First": 510000, "Second": 0})

		receipt.cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", receipt.journal_entry, "docstatus"), 2)
		sanction.reload()
		self.assertEqual(sanction.total_received, 0)

	def test_receipt_refused_when_the_locked_sanction_is_no_longer_submitted(self):
		sanction = self.sanction()
		sanction.submit()
		receipt = self.receipt(sanction.reload())
		frappe.db.set_value("Sanction", sanction.name, "docstatus", 2)  # as a concurrent cancel would leave it
		with self.assertRaisesRegex(frappe.ValidationError, "must be submitted"):
			receipt.before_submit()
		self.assertFalse(frappe.db.exists("Journal Entry", {"user_remark": ["like", f"%{receipt.name}%"]}))

	def test_receipt_cannot_exceed_the_instalment_balance(self):
		sanction = self.sanction()
		sanction.submit()
		sanction.reload()
		self.receipt(sanction, amount=500000).submit()
		with self.assertRaisesRegex(frappe.ValidationError, "balance"):
			self.receipt(sanction, amount=20000).submit()
		with self.assertRaisesRegex(frappe.ValidationError, "Third"):
			self.receipt(sanction, instalment="Third", amount=1000)

	def test_receipt_needs_a_submitted_sanction_and_a_bank_account_of_the_college(self):
		sanction = self.sanction()
		with self.assertRaisesRegex(frappe.ValidationError, "submitted"):
			self.receipt(sanction)
		sanction.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "bank or cash"):
			self.receipt(sanction.reload(), received_in=self.consumables_account)

	# acceptance 3: seed money from the Institution works the same way
	def test_institution_agency_is_seeded(self):
		self.assertEqual(frappe.db.get_value("Funding Agency", INSTITUTION_AGENCY, "agency_type"), "Institution")

	def test_seed_money_sanction_and_receipt(self):
		scheme = self.make_scheme("RSA Seed Money", [self.consumables], agency=INSTITUTION_AGENCY)
		sanction = self.sanction(
			heads=[(self.consumables, self.year1.name, 75000)], instalments=[("Single", 75000)],
			scheme=scheme, agency=INSTITUTION_AGENCY,
		)  # fmt: skip
		sanction.submit()
		sanction.reload()
		self.assertTrue(frappe.db.exists("Project", sanction.project))
		self.assertEqual(len(self.budgets(sanction.cost_center)), 1)
		receipt = self.receipt(sanction, instalment="Single")
		receipt.submit()
		credits = [e for e in self.gl(receipt.reload().journal_entry) if e.credit]
		self.assertEqual([(e.account, e.credit) for e in credits], [(sanction.liability_account, 75000)])

	# extension
	def test_extension_revises_the_end_date_with_its_order(self):
		sanction = self.sanction()
		sanction.submit()
		sanction.reload()
		revised = add_days(self.year2.end, 90)
		with self.assertRaisesRegex(frappe.ValidationError, "after"):
			sanction.extend_sanction(add_days(self.year2.end, -1), "EXT/1", today())
		sanction.extend_sanction(revised, "DST/EXT/7", today())
		sanction.reload()
		self.assertEqual(getdate(sanction.end_date), getdate(revised))
		[row] = sanction.extensions
		self.assertEqual((row.order_no, getdate(row.previous_end_date), getdate(row.revised_end_date)),
			("DST/EXT/7", getdate(self.year2.end), getdate(revised)))  # fmt: skip
		self.assertEqual(getdate(frappe.db.get_value("Project", sanction.project, "expected_end_date")), getdate(revised))

	# link to the proposal
	def make_proposal(self, status):
		call = frappe.get_doc(
			{"doctype": "Research Call", "call_title": f"RSA Call {frappe.generate_hash(length=6)}", "funding_agency": self.agency,
			 "funding_scheme": self.scheme, "deadline": today()}
		).insert().name  # fmt: skip
		proposal = frappe.get_doc(
			{"doctype": "Research Proposal", "title": "Sensors", "company": COLLEGE, "research_call": call,
			 "principal_investigator": self.pi, "budget": [{"budget_head": self.consumables, "amount": 1000}]}
		).insert()  # fmt: skip
		frappe.db.set_value("Research Proposal", proposal.name, {"docstatus": 1, "status": status})
		return proposal.name

	def test_sanction_links_only_to_a_sanctioned_proposal_of_the_same_scheme(self):
		with self.assertRaisesRegex(frappe.ValidationError, "not sanctioned"):
			self.sanction(research_proposal=self.make_proposal("Submitted to Agency"))
		proposal = self.make_proposal("Sanctioned")
		self.sanction(research_proposal=proposal).submit()
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			self.sanction(research_proposal=proposal).submit()
		other = self.make_scheme("RSA Other Scheme", [self.consumables])
		with self.assertRaisesRegex(frappe.ValidationError, "RSA Other Scheme"):
			self.sanction(research_proposal=self.make_proposal("Sanctioned"), scheme=other,
				heads=[(self.consumables, self.year1.name, 1000)], instalments=[("First", 1000)])  # fmt: skip
