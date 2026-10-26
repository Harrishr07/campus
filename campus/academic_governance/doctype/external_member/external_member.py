"""M02-01 / M02-05 External Member: a person from outside the institution who sits on bodies (organisation,
expertise) and is paid through a linked ERPNext Supplier. PAN and bank account are NOT stored here: Accounts keeps
them on the Supplier and Bank Account (the TDS owner, with their own audit trail), and this form shows them
read-only at permission level 1 (Accounts and the Principal). No version history, no log calls."""

import frappe
from frappe import _
from frappe.model.document import Document


class ExternalMember(Document):
	def validate(self):
		if self.supplier and frappe.db.exists(
			"External Member", {"supplier": self.supplier, "name": ["!=", self.name]}
		):
			frappe.throw(_("Supplier {0} is already linked to another External Member").format(self.supplier))

	@property
	def pan(self):
		return self.supplier and frappe.db.get_value("Supplier", self.supplier, "pan")

	@property
	def bank_account(self):
		return self.supplier and frappe.db.get_value(
			"Bank Account",
			{"party_type": "Supplier", "party": self.supplier},
			"name",
			order_by="is_default desc, creation",
		)

	@frappe.whitelist()
	def create_supplier(self):
		"""Create the Supplier this member is paid through and link it. The caller needs Supplier create rights."""
		self.check_permission("write")
		if self.supplier:
			frappe.throw(_("{0} is already linked to Supplier {1}").format(self.member_name, self.supplier))
		supplier = new_supplier(self.member_name)
		self.db_set("supplier", supplier)
		return supplier


def new_supplier(member_name, ignore_permissions=False):
	frappe.has_permission("Supplier", "create", throw=not ignore_permissions)
	supplier = frappe.new_doc("Supplier")
	supplier.supplier_name = member_name
	supplier.supplier_type = "Individual"
	supplier.supplier_group = frappe.db.get_single_value(
		"Buying Settings", "supplier_group"
	) or frappe.db.get_value("Supplier Group", {"is_group": 0})
	supplier.insert(ignore_permissions=ignore_permissions)
	return supplier.name
