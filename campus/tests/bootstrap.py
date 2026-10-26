"""before_tests: bring a fresh site (CI's test_site) to the baseline the campus-test sites keep: the setup wizard done,
fiscal years around today, the Gender masters and the selling price list. Idempotent; an existing test site is left
as it is."""

import frappe
from frappe.utils import now_datetime

GENDERS = ("Male", "Female", "Other")
PRICE_LIST = "Standard Selling"


def before_tests():
	frappe.clear_cache()
	complete_setup()
	clear_default_company()
	match_number_settings()
	make_fiscal_years()
	make_genders()
	make_price_list()
	frappe.db.commit()  # nosemgrep


def complete_setup():
	if frappe.get_list("Company"):
		return
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	year = now_datetime().year
	setup_complete(
		{
			"currency": "INR",
			"full_name": "Test User",
			"company_name": "_Test Company",
			"timezone": "Asia/Kolkata",
			"company_abbr": "_TC",
			"industry": "Education",
			"country": "India",
			"fy_start_date": f"{year}-01-01",
			"fy_end_date": f"{year}-12-31",
			"language": "english",
			"company_tagline": "Testing",
			"email": "test@example.com",
			"password": "test",
			"chart_of_accounts": "Standard",
		}
	)


def clear_default_company():
	"""The campus-test sites keep no default company: campus falls back to it in several places (company scope,
	formats, policies), so a default would stamp the wizard's _Test Company on records the tests make for their own
	colleges."""
	frappe.db.set_single_value("Global Defaults", "default_company", None)
	frappe.db.delete("DefaultValue", {"defkey": ["in", ["company", "Company"]]})
	frappe.clear_cache()


def match_number_settings():
	"""The wizard picks India's lakh grouping; the campus-test sites keep the plain format and rounding."""
	frappe.db.set_single_value(
		"System Settings", {"number_format": "#,###.##", "rounding_method": "Banker's Rounding (legacy)"}
	)


def make_fiscal_years():
	"""Calendar fiscal years from last year to two years ahead (tests date records into the next academic year)."""
	year = now_datetime().year
	for fy in range(year - 1, year + 3):
		start, end = f"{fy}-01-01", f"{fy}-12-31"
		overlapping = {"year_start_date": ("<=", end), "year_end_date": (">=", start)}
		if frappe.db.exists("Fiscal Year", overlapping) or frappe.db.exists("Fiscal Year", str(fy)):
			continue
		frappe.get_doc(
			{"doctype": "Fiscal Year", "year": str(fy), "year_start_date": start, "year_end_date": end}
		).insert(ignore_permissions=True)


def make_genders():
	for gender in GENDERS:
		if not frappe.db.exists("Gender", gender):
			frappe.get_doc({"doctype": "Gender", "gender": gender}).insert(ignore_permissions=True)


def make_price_list():
	if not frappe.db.exists("Price List", PRICE_LIST):
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": PRICE_LIST,
				"selling": 1,
				"currency": "INR",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
