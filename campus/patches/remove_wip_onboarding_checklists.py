"""M05-01 An unreviewed early build created Onboarding Checklist, Onboarding Checklist Item, Onboarding Checklist
Template and Onboarding Template Item. They were replaced by Student Onboarding (+ Item, Template, Template Item).
Drop any leftovers of the old names. Re-runnable: does nothing where they are already gone."""

import frappe

OLD_DOCTYPES = [
	"Onboarding Checklist",
	"Onboarding Checklist Item",
	"Onboarding Checklist Template",
	"Onboarding Template Item",
]


def execute():
	for name in OLD_DOCTYPES:
		if frappe.db.exists("DocType", name):
			frappe.delete_doc("DocType", name, force=True, ignore_permissions=True)
		frappe.db.sql_ddl(f"drop table if exists `tab{name}`")
