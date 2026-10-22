"""M09-02 Fill `company` on Bank Collection Rows created before the field existed. Re-runnable."""

import frappe


def execute():
	frappe.reload_doc("campus_finance", "doctype", "bank_collection_row")
	frappe.db.sql(
		"""update `tabBank Collection Row` row
		join `tabBank Collection Import` imp on imp.name = row.bank_collection_import
		set row.company = imp.company
		where row.company is null or row.company = ''"""
	)
