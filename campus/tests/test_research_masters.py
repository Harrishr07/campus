"""P3-T12 (M08-01) tests: research masters and settings. A Funding Scheme can be used for a company only when every
one of its Grant Budget Heads maps to a ledger account of that company; head accounts follow blueprint D9 (capital heads
capitalise to Asset accounts, revenue heads post to Expense accounts); Research Settings hold the per-company D9 accounts
and the interest treatment (grant liability by default, agency-configurable); Indexed Journal ISSNs are check-digit
validated."""

import frappe
from frappe.tests import UnitTestCase

from campus.research import api
from campus.research.issn import normalise_issn
from campus.tests.finance_factories import make_account, make_company_with_accounts
from campus.tests.utils import CampusTestCase

COLLEGE, ABBR = "Research Test College", "RSTC"
OTHER, OTHER_ABBR = "Research Other College", "RSTO"


class TestIssn(UnitTestCase):
	def test_valid_issns_normalise(self):
		self.assertEqual(normalise_issn("0378-5955"), "0378-5955")
		self.assertEqual(normalise_issn("03785955"), "0378-5955")
		self.assertEqual(normalise_issn(" 2434-561x "), "2434-561X")  # X check digit

	def test_invalid_issns_rejected(self):
		for bad in ("0378-5954", "1234", "ABCD-EFGH", "0378-59555"):
			with self.subTest(issn=bad), self.assertRaises(frappe.ValidationError):
				normalise_issn(bad)


class TestResearchMasters(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company_with_accounts(COLLEGE, ABBR)
		make_company_with_accounts(OTHER, OTHER_ABBR)

	def setUp(self):
		frappe.db.savepoint("research_masters_test")
		self.addCleanup(frappe.db.rollback, save_point="research_masters_test")
		self.consumables = make_account(COLLEGE, ABBR, "Research Consumables", "Indirect Expenses")
		self.travel = make_account(COLLEGE, ABBR, "Research Travel", "Indirect Expenses")
		self.equipment = f"Capital Equipment - {ABBR}"
		self.other_consumables = make_account(OTHER, OTHER_ABBR, "Research Consumables", "Indirect Expenses")
		self.agency = self.make_agency("RST Department of Science and Technology")

	# fixtures
	def make_agency(self, name, **values):
		return frappe.get_doc({"doctype": "Funding Agency", "agency_name": name, **values}).insert().name

	def make_item_group(self, name):
		if not frappe.db.exists("Item Group", name):
			parent = frappe.db.get_value(
				"Item Group", {"is_group": 1}, "name"
			)  # the bare test site may lack "All Item Groups"
			frappe.get_doc(
				{"doctype": "Item Group", "item_group_name": name, "parent_item_group": parent}
			).insert()
		return name

	def make_head(self, name, accounts=(), is_capital=0, item_groups=()):
		return (
			frappe.get_doc(
				{
					"doctype": "Grant Budget Head",
					"head_name": name,
					"is_capital": is_capital,
					"accounts": [{"company": company, "account": account} for company, account in accounts],
					"item_groups": [{"item_group": group} for group in item_groups],
				}  # fmt: skip
			)
			.insert()
			.name
		)

	def make_scheme(self, name, heads, instalments=()):
		return frappe.get_doc(
			{
				"doctype": "Funding Scheme",
				"scheme_name": name,
				"funding_agency": self.agency,
				"heads": [{"budget_head": head} for head in heads],
				"instalments": [{"instalment": label, "percent": pct} for label, pct in instalments],
			}  # fmt: skip
		).insert()

	def make_settings(self, company=COLLEGE, abbr=ABBR, **values):
		return frappe.get_doc(
			{
				"doctype": "Research Settings",
				"company": company,
				"grant_liability_parent": f"Current Liabilities - {abbr}",
				"grant_income_account": make_account(company, abbr, "Grant Income", "Indirect Income"),
				"deferred_capital_grant_account": make_account(
					company, abbr, "Deferred Capital Grant", "Non-Current Liabilities"
				),
				**values,
			}  # fmt: skip
		).insert()

	# acceptance 1: a scheme can't be used while a head lacks an account mapping for the company
	def test_scheme_usable_when_every_head_maps_for_company(self):
		consumables = self.make_head(
			"RST Consumables", [(COLLEGE, self.consumables), (OTHER, self.other_consumables)]
		)
		equipment = self.make_head("RST Equipment", [(COLLEGE, self.equipment)], is_capital=1)
		scheme = self.make_scheme("RST Core Research Grant", [consumables, equipment])
		self.make_settings()

		self.assertEqual(api.unmapped_heads(scheme.name, COLLEGE), [])
		api.validate_scheme_usable(scheme.name, COLLEGE)  # does not raise

	def test_scheme_unusable_when_a_head_lacks_mapping_for_company(self):
		consumables = self.make_head(
			"RST Consumables", [(COLLEGE, self.consumables), (OTHER, self.other_consumables)]
		)
		equipment = self.make_head("RST Equipment", [(COLLEGE, self.equipment)], is_capital=1)
		scheme = self.make_scheme("RST Core Research Grant", [consumables, equipment])
		self.make_settings(OTHER, OTHER_ABBR)

		self.assertEqual(api.unmapped_heads(scheme.name, OTHER), [equipment])
		with self.assertRaisesRegex(frappe.ValidationError, "RST Equipment"):
			api.validate_scheme_usable(scheme.name, OTHER)

	def test_scheme_unusable_without_research_settings_for_company(self):
		head = self.make_head("RST Consumables", [(COLLEGE, self.consumables)])
		scheme = self.make_scheme("RST Core Research Grant", [head])
		self.assertEqual(api.unmapped_heads(scheme.name, COLLEGE), [])
		with self.assertRaisesRegex(frappe.ValidationError, "Research Settings"):
			api.validate_scheme_usable(scheme.name, COLLEGE)

	def test_item_group_under_two_heads_of_a_scheme_is_refused(self):
		supplies = self.make_item_group("RST Lab Supplies")
		consumables = self.make_head("RST Consumables", [(COLLEGE, self.consumables)], item_groups=[supplies])
		travel = self.make_head("RST Travel", [(COLLEGE, self.travel)], item_groups=[supplies])
		with self.assertRaisesRegex(frappe.ValidationError, "RST Lab Supplies"):
			self.make_scheme("RST Overlapping Groups", [consumables, travel])
		# a head edited after the scheme was saved is caught when the scheme is used
		travel_doc = frappe.get_doc("Grant Budget Head", travel)
		travel_doc.item_groups = []
		travel_doc.save()
		scheme = self.make_scheme("RST Overlapping Later", [consumables, travel])
		self.make_settings()
		api.validate_scheme_usable(scheme.name, COLLEGE)
		travel_doc.append("item_groups", {"item_group": supplies})
		travel_doc.save()
		with self.assertRaisesRegex(frappe.ValidationError, "RST Lab Supplies"):
			api.validate_scheme_usable(scheme.name, COLLEGE)

	def test_scheme_without_heads_is_unusable(self):
		scheme = self.make_scheme("RST Empty Scheme", [])
		self.make_settings()
		with self.assertRaisesRegex(frappe.ValidationError, "no budget heads"):
			api.validate_scheme_usable(scheme.name, COLLEGE)

	def test_scheme_rejects_a_head_twice(self):
		head = self.make_head("RST Consumables", [(COLLEGE, self.consumables)])
		with self.assertRaisesRegex(frappe.ValidationError, "more than once"):
			self.make_scheme("RST Duplicate Heads", [head, head])

	# Funding Scheme instalment pattern and overhead
	def test_instalment_pattern_cannot_exceed_hundred_percent(self):
		head = self.make_head("RST Consumables", [(COLLEGE, self.consumables)])
		scheme = self.make_scheme("RST Two Instalments", [head], [("First", 60), ("Second", 40)])
		self.assertEqual(len(scheme.instalments), 2)
		with self.assertRaisesRegex(frappe.ValidationError, "100"):
			self.make_scheme("RST Over Instalments", [head], [("First", 70), ("Second", 40)])

	def test_overhead_percent_must_be_between_zero_and_hundred(self):
		head = self.make_head("RST Consumables", [(COLLEGE, self.consumables)])
		scheme = self.make_scheme("RST Overhead Scheme", [head])
		scheme.overhead_percent = 120
		with self.assertRaisesRegex(frappe.ValidationError, "Overhead"):
			scheme.save()

	# Grant Budget Head account mapping
	def test_head_account_must_belong_to_row_company(self):
		with self.assertRaisesRegex(frappe.ValidationError, OTHER):
			self.make_head("RST Wrong Company", [(OTHER, self.consumables)])

	def test_head_account_must_be_a_ledger(self):
		with self.assertRaisesRegex(frappe.ValidationError, "ledger"):
			self.make_head("RST Group Account", [(COLLEGE, f"Indirect Expenses - {ABBR}")])

	def test_capital_head_maps_to_asset_and_revenue_head_to_expense(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Asset"):
			self.make_head("RST Capital On Expense", [(COLLEGE, self.consumables)], is_capital=1)
		with self.assertRaisesRegex(frappe.ValidationError, "Expense"):
			self.make_head("RST Revenue On Asset", [(COLLEGE, self.equipment)])

	def test_capital_head_needs_a_fixed_asset_ledger(self):
		bank = make_account(COLLEGE, ABBR, "RST Grant Bank", "Bank Accounts", account_type="Bank")
		with self.assertRaisesRegex(frappe.ValidationError, "Fixed Asset"):
			self.make_head("RST Capital On Bank", [(COLLEGE, bank)], is_capital=1)

	def test_revenue_head_refuses_depreciation_stock_adjustment_and_round_off(self):
		for account_type in ("Depreciation", "Stock Adjustment", "Round Off"):
			account = make_account(
				COLLEGE, ABBR, f"RST {account_type}", "Indirect Expenses", account_type=account_type
			)
			with (
				self.subTest(account_type=account_type),
				self.assertRaisesRegex(frappe.ValidationError, account_type),
			):
				self.make_head(f"RST Revenue On {account_type}", [(COLLEGE, account)])

	def test_disabled_or_frozen_accounts_refused(self):
		disabled = make_account(COLLEGE, ABBR, "RST Disabled Expense", "Indirect Expenses", disabled=1)
		frozen = make_account(COLLEGE, ABBR, "RST Frozen Income", "Indirect Income", freeze_account="Yes")
		with self.assertRaisesRegex(frappe.ValidationError, "disabled"):
			self.make_head("RST On Disabled", [(COLLEGE, disabled)])
		with self.assertRaisesRegex(frappe.ValidationError, "frozen"):
			self.make_settings(grant_income_account=frozen)

	def test_head_rejects_duplicate_account_row(self):
		with self.assertRaisesRegex(frappe.ValidationError, "more than once"):
			self.make_head("RST Duplicate Row", [(COLLEGE, self.consumables), (COLLEGE, self.consumables)])

	def test_head_may_map_several_accounts_for_one_company(self):
		head = self.make_head("RST Consumables", [(COLLEGE, self.consumables), (COLLEGE, self.travel)])
		self.assertEqual(sorted(api.head_accounts(head, COLLEGE)), sorted([self.consumables, self.travel]))
		self.assertEqual(api.head_accounts(head, OTHER), [])

	# Research Settings (blueprint D9)
	def test_settings_one_per_company_with_liability_default_for_interest(self):
		settings = self.make_settings(pfms_unique_agency_code="RSTC0001")
		self.assertEqual(settings.name, COLLEGE)
		self.assertEqual(settings.interest_treatment, "Grant Liability")
		self.assertEqual(api.interest_treatment(COLLEGE, self.agency), "Grant Liability")
		with self.assertRaises(frappe.DuplicateEntryError):
			self.make_settings()

	def test_agency_overrides_interest_treatment(self):
		self.make_settings(
			interest_treatment="Grant Liability",
			interest_income_account=make_account(COLLEGE, ABBR, "Interest on Grant Funds", "Indirect Income"),
		)
		income_agency = self.make_agency("RST Private Foundation", interest_treatment="Interest Income")
		self.assertEqual(api.interest_treatment(COLLEGE, income_agency), "Interest Income")
		self.assertEqual(api.interest_treatment(COLLEGE, self.agency), "Grant Liability")

	def test_agency_override_to_income_needs_the_college_interest_income_account(self):
		self.make_settings()  # Grant Liability, no interest income account
		income_agency = self.make_agency("RST Private Foundation", interest_treatment="Interest Income")
		with self.assertRaisesRegex(frappe.ValidationError, "Interest Income Account"):
			api.interest_treatment(COLLEGE, income_agency)
		with self.assertRaisesRegex(frappe.ValidationError, "Interest Income Account"):
			api.interest_treatment(OTHER, income_agency)  # no Research Settings at all

	def test_interest_income_treatment_needs_an_income_account(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Interest Income Account"):
			self.make_settings(interest_treatment="Interest Income")

	def test_settings_accounts_validated_by_role_in_d9(self):
		cases = {
			"grant_liability_parent": (self.consumables, "group"),
			"grant_income_account": (self.consumables, "Income"),
			"deferred_capital_grant_account": (self.consumables, "Liability"),
		}
		for field, (account, message) in cases.items():
			with self.subTest(field=field), self.assertRaisesRegex(frappe.ValidationError, message):
				self.make_settings(**{field: account})
		with self.assertRaisesRegex(frappe.ValidationError, COLLEGE):
			self.make_settings(
				grant_income_account=make_account(OTHER, OTHER_ABBR, "Grant Income", "Indirect Income")
			)

	def test_settings_required_before_use(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Research Settings"):
			api.get_research_settings(OTHER)
		self.assertEqual(api.get_research_settings(self.make_settings().company).company, COLLEGE)

	# Indexed Journal
	def test_journal_issn_normalised_and_unique(self):
		journal = frappe.get_doc(
			{
				"doctype": "Indexed Journal",
				"journal_title": "RST Hearing Research",
				"issn": "03785955",
				"scopus": 1,
			}
		).insert()
		self.assertEqual(journal.issn, "0378-5955")
		with self.assertRaises(frappe.UniqueValidationError):
			frappe.get_doc(
				{"doctype": "Indexed Journal", "journal_title": "RST Copy", "issn": "0378-5955"}
			).insert()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Indexed Journal", "journal_title": "RST Bad", "issn": "0378-5954"}
			).insert()

	def test_journals_with_only_an_e_issn_share_a_blank_issn(self):
		for title, e_issn in (("RST Online One", "2434-561X"), ("RST Online Two", "0378-5955")):
			journal = frappe.get_doc(
				{"doctype": "Indexed Journal", "journal_title": title, "e_issn": e_issn}
			).insert()
			self.assertIsNone(journal.issn)
		with self.assertRaisesRegex(frappe.ValidationError, "ISSN or e-ISSN"):
			frappe.get_doc({"doctype": "Indexed Journal", "journal_title": "RST No ISSN"}).insert()
