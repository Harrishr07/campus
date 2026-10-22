"""M08-10 Consultancy Revenue Share: the distribution of one fully paid consultancy invoice's taxable value by the
project's rule (institution / faculty / staff %), the pools divided among the team by their shares.

Created only once the invoice is received in full (campus.research.consultancy.shareable_invoice); an invoice is shared
once. On submit, after locking the invoice row and reading its payment state again, each member is paid through an
HRMS Additional Salary on the next payroll; cancelling cancels them (refused by HRMS once a submitted slip paid one)."""

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from campus.research import consultancy
from campus.research.consultancy_rules import member_amounts, split_pools

RULE_FIELDS = ("institution_percent", "faculty_percent", "staff_percent")


class ConsultancyRevenueShare(Document):
	def validate(self):
		project = frappe.get_doc(consultancy.PROJECT, self.consultancy_project)
		invoice = consultancy.shareable_invoice(self.sales_invoice, project.name, self.name)
		self.set_split(project, invoice)

	def before_submit(self):
		consultancy.shareable_invoice(self.sales_invoice, self.consultancy_project, self.name, for_update=True)

	def on_submit(self):
		consultancy.post_additional_salaries(self)

	def on_cancel(self):
		consultancy.cancel_additional_salaries(self)

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
		self.set("members", [])
		for row, amount in zip(team, amounts, strict=True):
			self.append(
				"members",
				{"employee": row.employee, "employee_name": row.employee_name, "category": row.category, "share_percent": row.share_percent, "amount": amount},
			)  # fmt: skip
