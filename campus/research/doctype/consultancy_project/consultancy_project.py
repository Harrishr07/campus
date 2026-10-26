"""M08-10 Consultancy Project: a client (Customer) engagement of the college: estimate, signed agreement, deliverables and
the revenue-share rule (institution / faculty / staff %, the team sharing the faculty and staff pools).

Invoices are raised from the project once it is Agreed (campus.research.consultancy.make_sales_invoice). The rule and
the team are locked once a revenue share of the project is submitted; the college and client once it is invoiced."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from campus.research.consultancy import INVOICEABLE, SHARE, invoiced_value
from campus.research.consultancy_rules import check_rule, check_team

RULE_FIELDS = ("institution_percent", "faculty_percent", "staff_percent")


class ConsultancyProject(Document):
	def validate(self):
		self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		self.check_agreement()
		self.check_dates()
		check_rule(self.institution_percent, self.faculty_percent, self.staff_percent)
		self.check_team_company()
		check_team(self.team, {"Faculty": self.faculty_percent, "Staff": self.staff_percent})
		self.check_locks()

	def check_agreement(self):
		if self.status in INVOICEABLE and (not self.agreement_date or flt(self.agreement_value) <= 0):
			frappe.throw(
				_("Enter the agreement date and value of a project that is {0}.").format(
					_(self.status).lower()
				)
			)
		if self.is_new():
			return
		invoiced = invoiced_value(self.name)
		if flt(self.agreement_value, 2) < invoiced:
			frappe.throw(
				_("The agreement value can't be below what the project has been invoiced ({0}).").format(
					invoiced
				)
			)

	def check_dates(self):
		if self.start_date and self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("The end date can't be before the start date."))
		for row in self.deliverables:
			if row.status == "Delivered" and not row.delivered_on:
				frappe.throw(
					_("Row {0}: enter the date deliverable {1} was delivered.").format(
						row.idx, row.deliverable
					)
				)
			if row.status != "Delivered":
				row.delivered_on = None

	def check_team_company(self):
		employees = [self.principal_consultant] + [row.employee for row in self.team]
		companies = dict(
			frappe.get_all("Employee", {"name": ["in", employees]}, ["name", "company"], as_list=True)
		)
		others = sorted({e for e in employees if companies.get(e) != self.company})
		if others:
			frappe.throw(
				_("Employees {0} are not of {1}: the project's team is paid by its own college.").format(
					", ".join(others), self.company
				)
			)

	def check_locks(self):
		before = self.get_doc_before_save()
		if not before:
			return
		if (before.company, before.client) != (self.company, self.client) and invoiced_value(self.name):
			frappe.throw(_("The college and client of an invoiced project can't be changed."))
		if self.rule(before) != self.rule(self) and frappe.db.exists(
			SHARE, {"consultancy_project": self.name, "docstatus": 1}
		):
			frappe.throw(
				_("The revenue-share rule and team are locked: a revenue share of this project is submitted.")
			)

	@staticmethod
	def rule(doc):
		percents = tuple(flt(doc.get(field)) for field in RULE_FIELDS)
		return percents, sorted((row.employee, row.category, flt(row.share_percent)) for row in doc.team)
