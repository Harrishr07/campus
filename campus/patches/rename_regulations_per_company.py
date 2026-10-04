"""M02-04 Rename Regulation records from `<code>` to `<code>-<company abbr>` (names are per company).

Also drops the database-level unique index on `code` left over from the old `field:code` autoname."""

import frappe

from campus.campus_platform.doctype.regulation.regulation import regulation_name


def execute():
	drop_global_code_index()
	for row in frappe.get_all("Regulation", fields=["name", "code", "company"]):
		new_name = regulation_name(row.code, row.company)
		if row.name != new_name:
			frappe.rename_doc("Regulation", row.name, new_name, force=True, show_alert=False, rebuild_search=False)


def drop_global_code_index():
	"""`field:code` autoname made `code` globally unique at the database; names now carry the company."""
	if frappe.db.sql("SHOW INDEX FROM `tabRegulation` WHERE Key_name = 'code' AND Non_unique = 0"):
		frappe.db.sql_ddl("ALTER TABLE `tabRegulation` DROP INDEX `code`")
