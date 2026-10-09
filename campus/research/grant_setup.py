"""M08-03, M08-05 Grant set-up for a submitted Sanction (blueprint D9), reusing ERPNext records: one Project, one Cost
Center under the college's research cost centre, one Budget per revenue head account and the liability account "Grant
Received in Advance - <sanction>" that Grant Receipts credit.

Budgets run from the fiscal year of the start date to that of the end date, for the head's total, distributed by year
as sanctioned, with the scheme's Stop / Warn action on both the total and the cumulative-to-date amount. ERPNext budgets
only Profit and Loss accounts, so capital heads (Fixed Asset ledgers) get none.

Removal (sanction cancelled) is allowed only while nothing has been posted against the set-up."""

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe import _
from frappe.utils import flt

from campus.research.api import get_research_settings, head_accounts


class GrantSetup:
	def __init__(self, sanction):
		self.sanction = sanction
		self.company = sanction.company

	def create(self):
		settings = get_research_settings(self.company)
		if not settings.research_cost_center:
			frappe.throw(_("Set the Research Cost Centre in {0}'s Research Settings first.").format(self.company))
		sanction = self.sanction
		sanction.liability_account = self.make_liability_account(settings.grant_liability_parent)
		sanction.cost_center = self.make_cost_center(settings.research_cost_center)
		sanction.project = self.make_project()
		action = frappe.db.get_value("Funding Scheme", sanction.funding_scheme, "budget_action") or "Stop"
		for account, per_year in self.revenue_budget_lines().items():
			self.make_budget(account, per_year, action)

	def remove(self):
		sanction = self.sanction
		self.check_nothing_posted()
		records = (("Project", sanction.project), ("Cost Center", sanction.cost_center), ("Account", sanction.liability_account))
		# the sanction row still links them (its cancel isn't committed yet): unlink first so they can be deleted
		sanction.db_set({"project": None, "cost_center": None, "liability_account": None})
		cost_center = records[1][1]
		for name in frappe.get_all("Budget", {"cost_center": cost_center, "docstatus": 1}, pluck="name"):
			budget = frappe.get_doc("Budget", name)
			budget.flags.ignore_permissions = True
			budget.cancel()
		for name in frappe.get_all("Budget", {"cost_center": cost_center}, pluck="name"):
			frappe.delete_doc("Budget", name, ignore_permissions=True)
		for doctype, name in records:
			if name:
				self.delete(doctype, name)

	def delete(self, doctype, name):
		try:
			frappe.delete_doc(doctype, name, ignore_permissions=True)
		except frappe.LinkExistsError:
			frappe.throw(
				_("{0} can't be cancelled: its {1} {2} is used by other documents. Cancel or delete them first.").format(
					self.sanction.name, _(doctype), name
				)
			)

	def check_nothing_posted(self):
		sanction = self.sanction
		conditions = {"account": sanction.liability_account, "cost_center": sanction.cost_center, "project": sanction.project}
		for field, value in conditions.items():  # locking reads: a receipt committed while we waited is seen
			if value and frappe.db.get_value("GL Entry", {field: value}, "name", for_update=True):
				frappe.throw(
					_("{0} has accounting entries against its project, cost centre or liability account, so it can't be cancelled.").format(
						sanction.name
					)
				)

	def make_liability_account(self, parent):
		account = frappe.get_doc(
			{
				"doctype": "Account", "account_name": f"Grant Received in Advance - {self.sanction.name}",
				"parent_account": parent, "company": self.company, "is_group": 0,
				"account_currency": self.sanction.currency,
			}  # fmt: skip
		)
		account.flags.ignore_permissions = True
		return account.insert().name

	def make_cost_center(self, parent):
		cost_center = frappe.get_doc(
			{
				"doctype": "Cost Center", "cost_center_name": self.sanction.name, "parent_cost_center": parent,
				"company": self.company, "is_group": 0,
			}  # fmt: skip
		)
		cost_center.flags.ignore_permissions = True
		return cost_center.insert().name

	def make_project(self):
		sanction = self.sanction
		project = frappe.get_doc(
			{
				"doctype": "Project", "project_name": f"{sanction.title} ({sanction.name})", "company": self.company,
				"cost_center": sanction.cost_center, "expected_start_date": sanction.start_date,
				"expected_end_date": sanction.end_date, "status": "Open",
			}  # fmt: skip
		)
		project.flags.ignore_permissions = True
		return project.insert().name

	def revenue_budget_lines(self):
		"""{account: {fiscal year: amount}} for the revenue heads (each maps to one account, checked by the Sanction)."""
		lines = {}
		for row in self.sanction.heads:
			if row.is_capital:
				continue
			[account] = head_accounts(row.budget_head, self.company)
			per_year = lines.setdefault(account, {})
			per_year[row.fiscal_year] = per_year.get(row.fiscal_year, 0) + flt(row.amount)
		return lines

	def make_budget(self, account, per_year, action):
		total = sum(per_year.values())
		budget = frappe.get_doc(
			{
				"doctype": "Budget", "budget_against": "Cost Center", "company": self.company,
				"cost_center": self.sanction.cost_center, "account": account, "budget_amount": total,
				"from_fiscal_year": self.fiscal_year(self.sanction.start_date),
				"to_fiscal_year": self.fiscal_year(self.sanction.end_date),
				"distribution_frequency": "Yearly", "distribute_equally": 1,
				"applicable_on_booking_actual_expenses": 1, "action_if_annual_budget_exceeded": action,
				"action_if_accumulated_monthly_budget_exceeded": action,
				"applicable_on_purchase_order": 1, "action_if_annual_budget_exceeded_on_po": action,
				"action_if_accumulated_monthly_budget_exceeded_on_po": action,
			}  # fmt: skip
		)
		budget.flags.ignore_permissions = True
		budget.insert()  # ERPNext lays out one row per year on insert; the per-year amounts go in on the next save
		for row in budget.budget_distribution:
			row.amount = per_year.get(self.fiscal_year(row.start_date), 0)
			row.percent = flt(row.amount * 100 / total, 3)
		budget.distribute_equally = 0
		budget.save()
		budget.submit()

	def fiscal_year(self, date):
		return get_fiscal_year(date, company=self.company)[0]
