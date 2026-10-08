"""M07-07 Payroll setup for aided and self-financing staff, on HRMS payroll (no parallel payroll DocTypes).

Seeds, once and never over a college's edits:
- the pay components Basic, Dearness Allowance (DA), House Rent Allowance (HRA) and Academic Grade Pay (AGP);
- the HRMS India statutory components Provident Fund and Professional Tax get their Component Type (used by the HRMS
  PF and PT deduction reports) when it is blank;
- one draft Salary Structure per funding mode (Aided, Self-financing) for each college, for the college to review and
  submit. The rates (DA %, HRA %, PF %, PF wage ceiling, PT) live in those structure records: payroll reads only the
  records, these defaults are used only to create them.

Formulas are written on `base` (pay, from the Salary Structure Assignment) and `variable` (AGP), not on component
abbreviations, because the HRMS components already depend on payment days and HRMS refuses a payment-days formula
that also uses another payment-days component. Proration for leave without pay is therefore applied once per row.
See docs/usage/payroll.md.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Faculty"
FUNDING_MODES = ("Aided", "Self-financing")

# name, abbreviation, type
COMPONENTS = [
	("Basic", "B", "Earning"),
	("Dearness Allowance", "DA", "Earning"),
	("House Rent Allowance", "HRA", "Earning"),
	("Academic Grade Pay", "AGP", "Earning"),
]
STATUTORY_TYPES = {"Provident Fund": "Provident Fund", "Professional Tax": "Professional Tax"}

# funding mode -> earnings, deductions as (component, formula or None, amount)
STRUCTURES = {
	"Aided": (
		[
			("Basic", "base", 0),
			("Academic Grade Pay", "variable", 0),
			("Dearness Allowance", "(base + variable) * 0.50", 0),
			("House Rent Allowance", "(base + variable) * 0.10", 0),
		],
		[
			("Provident Fund", "(base + variable) * (1 + 0.50) * 0.12", 0),
			("Professional Tax", None, 208),
		],
	),
	"Self-financing": (
		[
			("Basic", "base", 0),
			("Dearness Allowance", "base * 0.10", 0),
			("House Rent Allowance", "base * 0.10", 0),
		],
		[
			("Provident Fund", "min(base * (1 + 0.10), 15000) * 0.12", 0),
			("Professional Tax", None, 208),
		],
	),
}


def setup_payroll():
	create_custom_fields({"Salary Structure": salary_structure_fields()}, update=True)
	seed_salary_components()
	for company in college_companies():
		seed_salary_structures(company)


def salary_structure_fields():
	return [
		{
			"fieldname": "oc_funding_mode", "fieldtype": "Select", "label": "Funding Mode", "insert_after": "company",
			"options": "\n" + "\n".join(FUNDING_MODES), "in_standard_filter": 1, "module": MODULE,
			"description": "The staff this structure is for; campus.faculty.api.assign_salary_structure picks it by the employee's funding mode.",
		}
	]  # fmt: skip


def seed_salary_components():
	for name, abbr, component_type in COMPONENTS:
		if frappe.db.exists("Salary Component", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Salary Component", "salary_component": name, "salary_component_abbr": abbr, "type": component_type,
				"description": name, "is_tax_applicable": 1, "depends_on_payment_days": 1,
			}
		).insert(ignore_permissions=True)  # fmt: skip
	type_statutory_components()


def type_statutory_components():
	"""Fill the HRMS India Component Type of Provident Fund / Professional Tax when blank, so HRMS's reports find them."""
	if not frappe.get_meta("Salary Component").has_field("component_type"):
		return
	for name, component_type in STATUTORY_TYPES.items():
		if frappe.db.exists("Salary Component", name) and not frappe.db.get_value("Salary Component", name, "component_type"):
			frappe.db.set_value("Salary Component", name, "component_type", component_type)


def college_companies():
	"""Colleges: companies with an Institution Profile that are not groups (a trust)."""
	profiles = frappe.get_all("Institution Profile", pluck="company")
	return frappe.get_all("Company", {"name": ["in", profiles], "is_group": 0}, pluck="name") if profiles else []


def structure_name(funding_mode, company):
	return f"{funding_mode} Staff - {frappe.get_cached_value('Company', company, 'abbr')}"


def seed_salary_structures(company):
	"""One draft Salary Structure per funding mode for `company`, unless it already has one for that mode."""
	currency = frappe.get_cached_value("Company", company, "default_currency")
	for mode, (earnings, deductions) in STRUCTURES.items():
		name = structure_name(mode, company)
		if frappe.db.exists("Salary Structure", name) or frappe.db.exists("Salary Structure", {"company": company, "oc_funding_mode": mode}):
			continue
		frappe.get_doc(
			{
				"doctype": "Salary Structure", "name": name, "company": company, "oc_funding_mode": mode, "currency": currency,
				"payroll_frequency": "Monthly", "is_active": "Yes",
				"earnings": rows(earnings), "deductions": rows(deductions, available_only=True),
			}
		).insert(ignore_permissions=True)  # fmt: skip


def rows(components, available_only=False):
	"""Structure rows; statutory deductions are added only where the HRMS component exists on the site."""
	return [
		{"salary_component": component, "amount_based_on_formula": 1 if formula else 0, "formula": formula, "amount": amount}
		for component, formula, amount in components
		if not available_only or frappe.db.exists("Salary Component", component)
	]
