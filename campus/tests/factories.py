"""Reusable test factories for OneBook Campus tests."""

import frappe


def make_company(name, abbr, is_group=0, parent_company=None):
	if frappe.db.exists("Company", name):
		return
	if not frappe.db.exists("Warehouse Type", "Transit"):  # test site has no ERPNext setup data
		frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert()
	frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": name,
			"abbr": abbr,
			"default_currency": "INR",
			"country": "India",
			"is_group": is_group,
			"parent_company": parent_company,
		}
	).insert()


def make_user(email, companies):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": "Academics User"}],
			}
		).insert()
	for company in companies:
		if not frappe.db.exists("User Permission", {"user": email, "allow": "Company", "for_value": company}):
			frappe.get_doc(
				{"doctype": "User Permission", "user": email, "allow": "Company", "for_value": company}
			).insert()
