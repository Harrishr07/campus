"""Shared fixtures for the research grant tests (P3-T14, P3-T15): colleges, heads, schemes, sanctions and receipts."""

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe.utils import add_days, today

from campus.research.setup import seed_research
from campus.tests.finance_factories import ensure_fiscal_years, make_account, make_company_with_accounts
from campus.tests.utils import CampusTestCase

COLLEGE, ABBR = "Research Sanction Test College", "RSAT"
OTHER, OTHER_ABBR = "Research Sanction Other College", "RSAO"


class SanctionFixtures(CampusTestCase):
	"""A college with Research Settings, two revenue heads, a capital head, a Stop scheme, a PI and a co-PI."""

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
		seed_research()
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
