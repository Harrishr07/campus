"""PR-02 Pilot fees: the fee categories' accounting defaults for the college and one Fee Structure per programme and
quota. Amounts are the profile's. A submitted Fee Structure is never edited: when its amounts differ from the
profile the run says so in its notes and leaves it."""

import frappe
from frappe import _

from campus.campus_finance.fee_heads import CAUTION_DEPOSIT, FEE_HEADS, seed_fee_categories, set_item_default

DEPOSIT_ACCOUNT = "Caution Deposits"
PRICE_LIST = "Standard Selling"


def ensure_selling_defaults():
	"""Confirm Joining raises a Sales Invoice, which needs a selling price list; the ERPNext setup wizard sets it, a bare site lacks it."""
	if not frappe.db.exists("Price List", PRICE_LIST):
		frappe.get_doc({"doctype": "Price List", "price_list_name": PRICE_LIST, "currency": "INR", "selling": 1, "enabled": 1}).insert(ignore_permissions=True)
	if not frappe.db.get_single_value("Selling Settings", "selling_price_list"):
		frappe.db.set_single_value("Selling Settings", "selling_price_list", PRICE_LIST)


def ensure_fees(profile, college, out):
	fees = profile.get("fees")
	if not fees:
		return
	seed_fee_categories()  # DML only; the categories exist after migrate
	accounts = ensure_fee_accounts(college, out)
	quotas = {q["code"] for q in profile.get("seats", {}).get("quotas", [])}
	for programme in fees["programmes"]:
		for quota in (None, *sorted(quotas & set(fees["components"]))):
			components = fees["components"][quota or "default"]
			ensure_fee_structure(out, college, programme, fees["academic_year"], quota, components, accounts)


def ensure_fee_accounts(company, out):
	"""Receivable account and cost centre of the college, and the income and deposit accounts the fee heads post to."""
	abbr = frappe.db.get_value("Company", company, "abbr")
	income = frappe.db.get_value("Company", company, "default_income_account") or f"Sales - {abbr}"
	deposit = ensure_deposit_account(company, abbr, out)
	cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name", order_by="creation, name")
	receivable = frappe.db.get_value("Company", company, "default_receivable_account")
	if not receivable:
		frappe.throw(_("Company {0} has no default receivable account.").format(company))
	for head in FEE_HEADS:
		category = frappe.get_doc("Fee Category", head)
		account = deposit if head == CAUTION_DEPOSIT else income
		row = next((d for d in category.item_defaults if d.company == company), None)
		if not row or row.income_account != account or row.selling_cost_center != cost_center:
			set_item_default(head, company, account, cost_center)
			out.updated["Fee Category"] += 1
	return {"receivable": receivable, "cost_center": cost_center}


def ensure_deposit_account(company, abbr, out):
	name = f"{DEPOSIT_ACCOUNT} - {abbr}"
	if not frappe.db.exists("Account", name):
		frappe.get_doc(
			{
				"doctype": "Account", "account_name": DEPOSIT_ACCOUNT, "company": company, "root_type": "Liability",
				"parent_account": f"Current Liabilities - {abbr}", "account_type": "",
			}
		).insert(ignore_permissions=True)
		out.created["Account"] += 1
	return name


def ensure_fee_structure(out, company, programme, year, quota, components, accounts):
	filters = {"company": company, "program": programme, "academic_year": year, "docstatus": ["<", 2]}
	filters["oc_admission_quota"] = quota or ["is", "not set"]
	name = frappe.db.exists("Fee Structure", filters)
	if name:
		note_differences(out, name, components)
		return
	doc = frappe.get_doc(
		{
			"doctype": "Fee Structure", "company": company, "program": programme, "academic_year": year,
			"oc_admission_quota": quota, "receivable_account": accounts["receivable"], "cost_center": accounts["cost_center"],
			"components": [{"fees_category": category, "amount": amount} for category, amount in components.items()],
		}
	).insert(ignore_permissions=True)
	doc.submit()
	out.created["Fee Structure"] += 1


def note_differences(out, name, components):
	stored = {row.fees_category: row.amount for row in frappe.get_doc("Fee Structure", name).components}
	if any(stored.get(category) != amount for category, amount in components.items()) or set(stored) != set(components):
		state = "submitted" if frappe.db.get_value("Fee Structure", name, "docstatus") == 1 else "a draft"
		out.notes.append(f"Fee Structure {name} differs from the profile; it is {state} and was left as it is.")
