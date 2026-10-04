"""M17-01 Back-fill `oc_company` on existing academic records with the site's default company."""

import frappe

from campus.campus_platform.company_scope import COMPANY_SCOPED_DOCTYPES, setup_company_fields


def execute():
	setup_company_fields()  # patches run before fixtures/after_migrate, so make sure the field exists
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		print("campus: no default company set; skipping oc_company back-fill")
		return
	for doctype in COMPANY_SCOPED_DOCTYPES:
		table = frappe.qb.DocType(doctype)
		(
			frappe.qb.update(table)
			.set(table.oc_company, company)
			.where(table.oc_company.isnull() | (table.oc_company == ""))
			.run()
		)
