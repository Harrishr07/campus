"""M08-10 Consultancy Revenue Share: the distribution of one consultancy invoice's taxable value, once received in full, by
the project's rule (institution / faculty / staff %), the pools divided among the team by their shares.

Created only once the invoice is received (campus.research.consultancy.shareable_invoice); an invoice is shared once.
It is approved through the approval engine (seeded policy: Accounts, then the Principal; on the mandatory approval list,
so it never submits without a policy) and no team member approves their own share. Members must be Active Employees of
the college when the share is made and when it is submitted. On submit, after locking the invoice row and reading its
payment state again, each member is paid through an HRMS Additional Salary on the next payroll; cancelling cancels them
(refused by HRMS once a submitted slip paid one)."""

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from campus.campus_platform.api import ApprovableDocument
from campus.research import consultancy
from campus.research.consultancy_rules import member_amounts, split_pools

RULE_FIELDS = ("institution_percent", "faculty_percent", "staff_percent")
MEMBER_FIELDS = ("employee", "employee_name", "category", "share_percent", "amount")


class ConsultancyRevenueShare(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		project = frappe.get_doc(consultancy.PROJECT, self.consultancy_project)
		invoice = consultancy.shareable_invoice(self.sales_invoice, project.name, self.name)
		self.set_split(project, invoice)
		consultancy.check_members(self)

	def before_submit(self):
		super().before_submit()
		consultancy.shareable_invoice(
			self.sales_invoice, self.consultancy_project, self.name, for_update=True
		)

	def on_submit(self):
		consultancy.post_additional_salaries(self)

	def on_cancel(self):
		consultancy.cancel_additional_salaries(self)

	def approval_excluded_users(self):
		employees = [m.employee for m in self.members]
		return [
			u for u in frappe.get_all("Employee", {"name": ["in", employees or [""]]}, pluck="user_id") if u
		]

	def set_split(self, project, invoice):
		self.company, self.client = project.company, project.client
		self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		self.taxable_amount = flt(invoice.base_net_total, 2)
		for field in RULE_FIELDS:
			self.set(field, project.get(field))
		self.institution_amount, self.faculty_amount, self.staff_amount = split_pools(
			self.taxable_amount, self.institution_percent, self.faculty_percent, self.staff_percent
		)
		team = [row.as_dict() for row in project.team]
		amounts = member_amounts(team, {"Faculty": self.faculty_amount, "Staff": self.staff_amount})
		members = [
			{**{f: row.get(f) for f in MEMBER_FIELDS[:-1]}, "amount": amount}
			for row, amount in zip(team, amounts, strict=True)
		]
		current = [{f: m.get(f) for f in MEMBER_FIELDS} for m in self.members]
		if [self.member_key(m) for m in current] != [
			self.member_key(m) for m in members
		]:  # rows kept when unchanged (approval lock)
			self.set("members", members)

	@staticmethod
	def member_key(member):
		return (member["employee"], member["category"], flt(member["share_percent"]), flt(member["amount"]))
