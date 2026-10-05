"""Test factories for Campus Finance (P1-T23): a college with accounts, fee defaults, students and a fee schedule."""

import frappe
from frappe.utils import add_days, today

from campus.campus_finance.fee_heads import CAUTION_DEPOSIT, FEE_HEADS, FINE, TUITION, set_item_default
from campus.campus_finance.setup import setup_finance
from campus.tests.factories import make_company

FISCAL_YEARS = range(2024, 2029)


def ensure_fiscal_years():
	for year in FISCAL_YEARS:
		if not frappe.db.exists("Fiscal Year", str(year)):
			frappe.get_doc(
				{"doctype": "Fiscal Year", "year": str(year), "year_start_date": f"{year}-01-01", "year_end_date": f"{year}-12-31"}
			).insert()


def ensure_selling_setup():
	"""The test site has no ERPNext setup data: invoices need a selling price list."""
	if not frappe.db.exists("Price List", "Standard Selling"):
		frappe.get_doc(
			{"doctype": "Price List", "price_list_name": "Standard Selling", "currency": "INR", "selling": 1, "enabled": 1}
		).insert()
	frappe.db.set_single_value("Selling Settings", "selling_price_list", "Standard Selling")


def make_account(company, abbr, name, parent, **fields):
	full = f"{name} - {abbr}"
	if not frappe.db.exists("Account", full):
		frappe.get_doc(
			{"doctype": "Account", "account_name": name, "company": company, "parent_account": f"{parent} - {abbr}", **fields}
		).insert()
	return full


def make_company_with_accounts(name, abbr):
	"""make_company, plus the chart of accounts the bare test site may have skipped."""
	make_company(name, abbr)
	if not frappe.db.exists("Account", {"company": name}):
		frappe.local.flags.ignore_chart_of_accounts = False
		frappe.get_doc("Company", name).save()


def make_finance_company(name, abbr):
	"""A company with a chart of accounts, fiscal years, fee defaults for every head and a Challan Format.

	Returns a dict of the accounts and cost centre fee defaults point to. Idempotent.
	"""
	setup_finance()
	ensure_fiscal_years()
	ensure_selling_setup()
	make_company_with_accounts(name, abbr)
	income = f"Sales - {abbr}"
	deposit = make_account(
		name, abbr, "Caution Deposits", "Current Liabilities", root_type="Liability", account_type=""
	)
	bank = make_account(name, abbr, "Collection Bank", "Bank Accounts", account_type="Bank", root_type="Asset")
	cost_center = frappe.db.get_value("Cost Center", {"company": name, "is_group": 0}, "name")
	for head in FEE_HEADS:
		set_item_default(head, name, deposit if head == CAUTION_DEPOSIT else income, cost_center)
	make_challan_format(name, bank)
	return {"income": income, "deposit": deposit, "bank": bank, "cost_center": cost_center}


def make_challan_format(company, receiving_account, **values):
	if frappe.db.exists("Challan Format", company):
		frappe.delete_doc("Challan Format", company)
	return frappe.get_doc(
		{
			"doctype": "Challan Format", "company": company, "bank_name": "State Bank of India", "branch": "Main",
			"account_number": "30000000001", "ifsc": "SBIN0000001", "receiving_account": receiving_account, **values,
		}
	).insert()


def make_year_and_program(company, program, year_name):
	if not frappe.db.exists("Academic Year", year_name):
		frappe.get_doc(
			{"doctype": "Academic Year", "academic_year_name": year_name, "year_start_date": f"{today()[:4]}-01-01",
			 "year_end_date": f"{today()[:4]}-12-31"}
		).insert()  # fmt: skip
	if not frappe.db.exists("Program", program):
		frappe.get_doc({"doctype": "Program", "program_name": program, "oc_company": company}).insert()


def make_enrolled_students(company, program, year_name, count, prefix):
	"""`count` students enrolled (submitted) in `program`, in one active Student Group; returns (group, students)."""
	students = []
	was_importing = frappe.flags.in_import
	frappe.flags.in_import = True  # bulk load: skip Frappe's 60-users-per-minute creation throttle
	for n in range(count):
		student = frappe.get_doc(
			{
				"doctype": "Student", "enabled": 1, "first_name": f"{prefix}{n:03d}", "student_email_id": f"{prefix.lower()}{n:03d}@fees.example.com",
				"oc_company": company,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Program Enrollment", "student": student.name, "program": program, "academic_year": year_name,
				"enrollment_date": today(),
			}
		).insert().submit()
		students.append(student.name)
	frappe.flags.in_import = was_importing
	group = frappe.get_doc(
		{
			"doctype": "Student Group", "student_group_name": f"{prefix} Group", "academic_year": year_name,
			"group_based_on": "Batch", "program": program, "students": [{"student": s} for s in students],
		}
	).insert()
	return group.name, students


def make_fee_structure(company, program, year_name, components, accounts, **values):
	"""A submitted Fee Structure; `components` maps fee category to amount."""
	doc = frappe.get_doc(
		{
			"doctype": "Fee Structure", "company": company, "program": program, "academic_year": year_name,
			"receivable_account": frappe.get_cached_value("Company", company, "default_receivable_account"),
			"cost_center": accounts["cost_center"],
			"components": [{"fees_category": c, "amount": a} for c, a in components.items()], **values,
		}
	).insert()
	return doc.submit()


def make_fee_schedule(structure, group, due_date=None, submit=True):
	doc = frappe.get_doc(
		{
			"doctype": "Fee Schedule", "fee_structure": structure.name, "company": structure.company,
			"program": structure.program, "academic_year": structure.academic_year, "due_date": due_date or add_days(today(), 30),
			"receivable_account": structure.receivable_account, "cost_center": structure.cost_center,
			"components": [
				{"fees_category": c.fees_category, "amount": c.amount, "total": c.total, "item": c.item} for c in structure.components
			],
			"student_groups": [{"student_group": group}],
		}
	).insert()
	return doc.submit() if submit else doc
