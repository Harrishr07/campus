"""M02-01 One-off move of PAN values stored on External Member (first version) to the Supplier, where Accounts keeps
them. Never overwrites a PAN already on the Supplier; creates the Supplier when the member had none. Re-runnable."""

import frappe

from campus.academic_governance.doctype.external_member.external_member import new_supplier


def move_stored_pan_to_suppliers():
	if not frappe.db.has_column("External Member", "pan"):
		return
	for name, supplier, pan in frappe.db.sql(
		"select name, supplier, pan from `tabExternal Member` where ifnull(pan, '') != ''"
	):
		if not supplier:
			supplier = new_supplier(
				frappe.db.get_value("External Member", name, "member_name"), ignore_permissions=True
			)
			frappe.db.set_value("External Member", name, "supplier", supplier, update_modified=False)
		if not frappe.db.get_value("Supplier", supplier, "pan"):
			frappe.db.set_value("Supplier", supplier, "pan", pan)
		frappe.db.sql("update `tabExternal Member` set pan = null where name = %s", name)
