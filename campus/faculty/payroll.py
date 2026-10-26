"""M07-07 Salary Structure Assignment by funding mode.

An employee gets the submitted, active Salary Structure of their own company whose Funding Mode matches the employee's
(Employee.oc_funding_mode). One assignment per employee and From Date: asking again returns the existing submitted one
unchanged; an existing draft, or one on a structure of another funding mode, is refused for HR to sort out.
An increment or promotion is an HRMS Employee Promotion plus a new assignment from the promotion date with the new pay.
"""

import frappe
from frappe import _


def assign(employee, from_date, base, variable=0):
	"""Name of the Salary Structure Assignment of `employee` from `from_date`; created and submitted when missing.

	Runs with the caller's permissions (HR creates and submits Salary Structure Assignments).
	"""
	if not frappe.db.get_value(
		"Employee", employee, "name", for_update=True
	):  # also serialises one employee's assignments
		frappe.throw(_("Employee {0} not found.").format(employee), frappe.DoesNotExistError)
	if not base or base <= 0:
		frappe.throw(_("Base pay must be more than zero."))
	existing = existing_assignment(employee, from_date)
	if existing:
		return existing
	company, funding_mode = frappe.db.get_value("Employee", employee, ["company", "oc_funding_mode"])
	assignment = frappe.get_doc(
		{
			"doctype": "Salary Structure Assignment", "employee": employee, "company": company, "from_date": from_date,
			"salary_structure": structure_for(company, funding_mode), "base": base, "variable": variable,
			"currency": frappe.get_cached_value("Company", company, "default_currency"),
		}
	).insert()  # fmt: skip
	assignment.submit()
	return assignment.name


def existing_assignment(employee, from_date):
	"""The submitted assignment from `from_date` on the employee's funding mode, or None; refuses a draft or another mode.

	Locking read: it runs after the Employee lock, so it must not see the transaction's older snapshot."""
	row = frappe.db.get_value(
		"Salary Structure Assignment", {"employee": employee, "from_date": from_date, "docstatus": ["<", 2]},
		["name", "docstatus", "salary_structure"], as_dict=True, for_update=True,
	)  # fmt: skip
	if not row:
		return None
	if row.docstatus == 0:
		frappe.throw(
			_(
				"Draft Salary Structure Assignment {0} exists for this date: submit or delete it first."
			).format(row.name)
		)
	structure_mode = frappe.db.get_value("Salary Structure", row.salary_structure, "oc_funding_mode")
	if structure_mode != frappe.db.get_value("Employee", employee, "oc_funding_mode"):
		frappe.throw(
			_(
				"Salary Structure Assignment {0} for this date uses {1}, which is not for the employee's funding mode: cancel it first."
			).format(row.name, row.salary_structure)
		)
	return row.name


def structure_for(company, funding_mode):
	if not funding_mode:
		frappe.throw(_("Set the Funding Mode on the employee before assigning a salary structure."))
	structures = frappe.get_all(
		"Salary Structure",
		{"company": company, "oc_funding_mode": funding_mode, "docstatus": 1, "is_active": "Yes"},
		pluck="name",
	)
	if not structures:
		frappe.throw(
			_(
				"No submitted, active Salary Structure for {0} staff in {1}. Review and submit the {0} structure first."
			).format(_(funding_mode), company)
		)
	if len(structures) > 1:
		frappe.throw(
			_(
				"More than one active Salary Structure for {0} staff in {1}: {2}. Set the old ones inactive."
			).format(_(funding_mode), company, ", ".join(structures))
		)
	return structures[0]
