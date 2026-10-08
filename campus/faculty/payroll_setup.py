"""M07-07 Payroll setup for aided and self-financing staff, on HRMS payroll (no parallel payroll DocTypes).

Seeds, and never over a college's edits:
- the pay components Basic, Dearness Allowance (DA), House Rent Allowance (HRA) and Academic Grade Pay (AGP), when
  missing (DA and AGP round to the nearest rupee);
- once per site (flag STATUTORY_FLAG): the Component Type of HRMS's Provident Fund and Professional Tax when blank
  (for the HRMS PF and PT reports), Provident Fund not by payment days (it is computed on the prorated wage) and
  rounded, and rounding on DA and AGP;
- once per college (Company.oc_payroll_templates_seeded): one draft Salary Structure per funding mode (Aided,
  Self-financing) with PLACEHOLDER rates, for the college to review and submit. A deleted one is not seeded again.

The rates (DA %, HRA %, PF % and wage ceiling) live in those structure records: payroll reads only the records, the
defaults below are used only to create them. Earnings are written on `base` (pay, from the Salary Structure
Assignment) and `variable` (AGP), because HRMS's Basic and HRA depend on payment days and HRMS refuses a payment-days
formula that reads another payment-days component. Provident Fund does not depend on payment days, so it reads the
prorated Basic, AGP and DA. Professional Tax is seeded disabled (amount 0, a false Condition with a TODO): state slabs
must be entered by the college. See docs/usage/payroll.md.
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

STATUTORY_FLAG = "campus_payroll_statutory_wired"
ROUNDED = ("Dearness Allowance", "Academic Grade Pay", "Provident Fund")
SEED_NOTE = "PLACEHOLDER RATES - review every rate before submitting (seeded by OneBook Campus; see the payroll guide)."
PT_TODO = '0 and "TODO: enter your state Professional Tax slab as the condition and amount"'

# funding mode -> earnings, deductions as (component, formula or None, amount, condition). In formulas {B}, {AGP} and
# {DA} are replaced by the site's abbreviations of Basic, Academic Grade Pay and Dearness Allowance.
STRUCTURES = {
	"Aided": (
		[
			("Basic", "base", 0, None),
			("Academic Grade Pay", "variable", 0, None),
			("Dearness Allowance", "(base + variable) * 0.50", 0, None),
			("House Rent Allowance", "(base + variable) * 0.10", 0, None),
		],
		[
			("Provident Fund", "min({B} + {AGP} + {DA}, 15000) * 0.12", 0, None),
			("Professional Tax", None, 0, PT_TODO),
		],
	),
	"Self-financing": (
		[
			("Basic", "base", 0, None),
			("Dearness Allowance", "base * 0.10", 0, None),
			("House Rent Allowance", "base * 0.10", 0, None),
		],
		[
			("Provident Fund", "min({B} + {DA}, 15000) * 0.12", 0, None),
			("Professional Tax", None, 0, PT_TODO),
		],
	),
}


def setup_payroll():
	create_custom_fields({"Salary Structure": salary_structure_fields(), "Company": company_fields()}, update=True)
	seed_salary_components()
	for company in college_companies():
		seed_salary_structures(company)


def salary_structure_fields():
	return [
		{
			"fieldname": "oc_funding_mode", "fieldtype": "Select", "label": "Funding Mode", "insert_after": "company",
			"options": "\n" + "\n".join(FUNDING_MODES), "in_standard_filter": 1, "module": MODULE,
			"description": "The staff this structure is for; campus.faculty.api.assign_salary_structure picks it by the employee's funding mode.",
		},
		{
			"fieldname": "oc_seed_note", "fieldtype": "Small Text", "label": "Review Note", "insert_after": "oc_funding_mode",
			"module": MODULE, "no_copy": 1,
		},
	]  # fmt: skip


def company_fields():
	return [
		{
			"fieldname": "oc_payroll_templates_seeded", "fieldtype": "Check", "label": "Payroll Templates Seeded", "insert_after": "default_payroll_payable_account",
			"hidden": 1, "read_only": 1, "no_copy": 1, "module": MODULE,
		}
	]  # fmt: skip


def seed_salary_components():
	for name, abbr, component_type in COMPONENTS:
		if frappe.db.exists("Salary Component", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Salary Component", "salary_component": name, "salary_component_abbr": abbr, "type": component_type,
				"description": name, "is_tax_applicable": 1, "depends_on_payment_days": 1, "round_to_the_nearest_integer": int(name in ROUNDED),
			}
		).insert(ignore_permissions=True)  # fmt: skip
	type_statutory_components()


def type_statutory_components():
	"""Once per site: wire HRMS's statutory components and round DA, AGP and PF. Later edits by the college are kept."""
	if frappe.db.get_global(STATUTORY_FLAG):
		return
	if frappe.get_meta("Salary Component").has_field("component_type"):
		for name, component_type in STATUTORY_TYPES.items():
			if frappe.db.exists("Salary Component", name) and not frappe.db.get_value("Salary Component", name, "component_type"):
				frappe.db.set_value("Salary Component", name, "component_type", component_type)
	if frappe.db.exists("Salary Component", "Provident Fund"):
		frappe.db.set_value("Salary Component", "Provident Fund", "depends_on_payment_days", 0)
	for name in ROUNDED:
		if frappe.db.exists("Salary Component", name):
			frappe.db.set_value("Salary Component", name, "round_to_the_nearest_integer", 1)
	frappe.db.set_global(STATUTORY_FLAG, 1)


def college_companies():
	"""Colleges: companies with an Institution Profile that are not groups (a trust)."""
	profiles = frappe.get_all("Institution Profile", pluck="company")
	return frappe.get_all("Company", {"name": ["in", profiles], "is_group": 0}, pluck="name") if profiles else []


def structure_name(funding_mode, company):
	return f"{funding_mode} Staff - {frappe.get_cached_value('Company', company, 'abbr')}"


def seed_salary_structures(company):
	"""Once per company: a draft Salary Structure per funding mode, unless one exists for that mode."""
	if frappe.db.get_value("Company", company, "oc_payroll_templates_seeded"):
		return
	currency = frappe.get_cached_value("Company", company, "default_currency")
	abbrs = abbreviations()
	for mode, (earnings, deductions) in STRUCTURES.items():
		name = structure_name(mode, company)
		if frappe.db.exists("Salary Structure", name) or frappe.db.exists("Salary Structure", {"company": company, "oc_funding_mode": mode}):
			continue
		frappe.get_doc(
			{
				"doctype": "Salary Structure", "name": name, "company": company, "oc_funding_mode": mode, "currency": currency,
				"payroll_frequency": "Monthly", "is_active": "Yes", "oc_seed_note": SEED_NOTE,
				"earnings": rows(earnings, abbrs), "deductions": rows(deductions, abbrs, available_only=True),
			}
		).insert(ignore_permissions=True)  # fmt: skip
	frappe.db.set_value("Company", company, "oc_payroll_templates_seeded", 1)


def abbreviations():
	names = {"B": "Basic", "AGP": "Academic Grade Pay", "DA": "Dearness Allowance"}
	return {key: frappe.db.get_value("Salary Component", name, "salary_component_abbr") or key for key, name in names.items()}


def rows(components, abbrs, available_only=False):
	"""Structure rows; statutory deductions are added only where the HRMS component exists on the site."""
	return [
		{
			"salary_component": component, "amount_based_on_formula": 1 if formula else 0,
			"formula": formula.format(**abbrs) if formula else None, "amount": amount, "condition": condition,
		}
		for component, formula, amount, condition in components
		if not available_only or frappe.db.exists("Salary Component", component)
	]  # fmt: skip
