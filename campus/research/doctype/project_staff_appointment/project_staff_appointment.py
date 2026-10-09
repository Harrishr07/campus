"""M08-09 Project Staff Appointment: a JRF / SRF / Project Assistant on a sanctioned project, reusing HRMS payroll.

The appointee is an Employee of the college with employment type "Project Staff". Submitting the appointment sets the
Employee's contract end date to the sanction end and their designation, and submits a Salary Structure Assignment of
the fellowship structure from the appointment date with the sanction's cost centre as the only payroll cost centre.
Payroll then accrues the salary on that cost centre; the accrual's salary rows take the sanction head their account
maps to (campus.research.budget_control), so they count against the head's Budget and in the Utilisation Certificate.
Every earning of the structure must post to an account of one revenue head of the sanction (Manpower), checked here so
payroll is not refused later. An employee holds one appointment at a time; a closed sanction takes no appointments."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from campus.research.api import check_sanction_open
from campus.research.setup import PROJECT_STAFF

SANCTION_FIELDS = ["name", "docstatus", "company", "project", "cost_center", "start_date", "end_date", "project_closure"]


class ProjectStaffAppointment(Document):
	def validate(self):
		sanction = self.get_sanction()
		self.company, self.project, self.cost_center = sanction.company, sanction.project, sanction.cost_center
		self.to_date = sanction.end_date
		self.check_employee()
		self.check_period(sanction)
		self.check_structure()
		self.budget_head = self.salary_head(sanction)
		self.check_one_appointment()

	def before_submit(self):
		sanction = self.get_sanction(for_update=True)
		self.check_one_appointment(lock=True)
		frappe.db.set_value("Employee", self.employee, {"contract_end_date": sanction.end_date, "designation": self.designation})
		self.salary_structure_assignment = self.make_assignment(sanction)

	def on_cancel(self):
		name = self.salary_structure_assignment
		if name and frappe.db.get_value("Salary Structure Assignment", name, "docstatus") == 1:
			assignment = frappe.get_doc("Salary Structure Assignment", name)
			assignment.flags.ignore_permissions = True
			assignment.cancel()

	def get_sanction(self, for_update=False):
		sanction = frappe.db.get_value("Sanction", self.sanction, SANCTION_FIELDS, as_dict=True, for_update=for_update)
		if not sanction or sanction.docstatus != 1:
			frappe.throw(_("Sanction {0} must be submitted.").format(self.sanction))
		check_sanction_open(sanction.name, sanction.project_closure)
		return sanction

	def check_employee(self):
		company, employment_type = frappe.db.get_value("Employee", self.employee, ["company", "employment_type"])
		if company != self.company:
			frappe.throw(_("Employee {0} is not an employee of {1}.").format(self.employee, self.company))
		if employment_type != PROJECT_STAFF:
			frappe.throw(_("Employee {0} must have the employment type {1}.").format(self.employee, _(PROJECT_STAFF)))

	def check_period(self, sanction):
		if not getdate(sanction.start_date) <= getdate(self.from_date) <= getdate(sanction.end_date):
			frappe.throw(
				_("The From Date must be inside the sanction period ({0} to {1}).").format(
					frappe.format(sanction.start_date, "Date"), frappe.format(sanction.end_date, "Date")
				)
			)

	def check_structure(self):
		structure = frappe.db.get_value("Salary Structure", self.salary_structure, ["docstatus", "is_active", "company"], as_dict=True)
		if not structure or structure.docstatus != 1 or structure.is_active != "Yes" or structure.company != self.company:
			frappe.throw(_("Salary Structure {0} must be a submitted, active structure of {1}.").format(self.salary_structure, self.company))

	def salary_head(self, sanction):
		"""The one revenue head of the sanction every earning of the structure posts to."""
		heads = frappe.get_all(
			"Sanction Head", {"parent": sanction.name, "parenttype": "Sanction", "is_capital": 0}, pluck="budget_head"
		)
		found = set()
		for component in frappe.get_all(
			"Salary Detail", {"parent": self.salary_structure, "parenttype": "Salary Structure", "parentfield": "earnings"},
			pluck="salary_component",
		):  # fmt: skip
			account = frappe.db.get_value("Salary Component Account", {"parent": component, "company": self.company}, "account")
			head = account and frappe.db.get_value(
				"Grant Budget Head Account",
				{"parent": ["in", heads or [""]], "parenttype": "Grant Budget Head", "company": self.company, "account": account},
				"parent",
			)
			if not head:
				frappe.throw(
					_("Salary component {0} posts to {1}, which is not an account of a budget head of Sanction {2}.").format(
						component, account or _("no account of {0}").format(self.company), sanction.name
					)
				)
			found.add(head)
		if len(found) != 1:
			frappe.throw(_("The earnings of Salary Structure {0} must post to one budget head of the sanction.").format(self.salary_structure))
		return found.pop()

	def check_one_appointment(self, lock=False):
		other = frappe.db.get_value(
			self.doctype,
			{"employee": self.employee, "docstatus": 1, "name": ["!=", self.name], "to_date": [">=", self.from_date]},
			"name", for_update=lock,
		)  # fmt: skip
		if other:
			frappe.throw(_("Employee {0} already holds Project Staff Appointment {1}.").format(self.employee, other))

	def make_assignment(self, sanction):
		assignment = frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment", "employee": self.employee, "salary_structure": self.salary_structure,
				"company": self.company, "from_date": self.from_date, "base": self.base,
				"currency": frappe.get_cached_value("Company", self.company, "default_currency"),
				"payroll_cost_centers": [{"cost_center": sanction.cost_center, "percentage": 100}],
			}  # fmt: skip
		)
		assignment.flags.ignore_permissions = True
		assignment.insert()
		assignment.submit()
		return assignment.name
