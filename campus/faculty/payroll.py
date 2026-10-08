"""M07-07 Salary Structure Assignment by funding mode.

An employee gets the submitted, active Salary Structure of their own company whose Funding Mode matches the employee's
(Employee.oc_funding_mode). One assignment per employee and From Date: asking again returns the existing one unchanged.
An increment or promotion is an HRMS Employee Promotion plus a new assignment from the promotion date with the new pay.
"""

import frappe
from frappe import _


def assign(employee, from_date, base, variable=0):
	"""Name of the Salary Structure Assignment of `employee` from `from_date`; created and submitted when missing.

	Runs with the caller's permissions (HR creates and submits Salary Structure Assignments).
	"""
	frappe.db.get_value("Employee", employee, "name", for_update=True)  # serialise assignments of one employee
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
	"""Locking read: it runs after the Employee lock, so it must not see the transaction's older snapshot."""
	return frappe.db.get_value(
		"Salary Structure Assignment", {"employee": employee, "from_date": from_date, "docstatus": ["<", 2]}, "name", for_update=True
	)


def structure_for(company, funding_mode):
	if not funding_mode:
		frappe.throw(_("Set the Funding Mode on the employee before assigning a salary structure."))
	structures = frappe.get_all(
		"Salary Structure", {"company": company, "oc_funding_mode": funding_mode, "docstatus": 1, "is_active": "Yes"}, pluck="name"
	)
	if not structures:
		frappe.throw(
			_("No submitted, active Salary Structure for {0} staff in {1}. Review and submit the {0} structure first.").format(
				_(funding_mode), company
			)
		)
	if len(structures) > 1:
		frappe.throw(
			_("More than one active Salary Structure for {0} staff in {1}: {2}. Set the old ones inactive.").format(
				_(funding_mode), company, ", ".join(structures)
			)
		)
	return structures[0]
