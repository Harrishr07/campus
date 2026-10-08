"""M02-01 / M02-05 External Member: a person from outside the institution who sits on bodies (organisation,
expertise) and is paid through a linked ERPNext Supplier. PAN and the bank account are sensitive: they sit at
permission level 1 (Accounts and the Principal), are never logged or echoed in messages, and the document keeps
no version history. Name, TDS and payment data live on the Supplier; nothing of it is copied here."""

import re

import frappe
from frappe import _
from frappe.model.document import Document

PAN_FORMAT = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


class ExternalMember(Document):
	def validate(self):
		self.validate_pan()
		self.validate_bank_account()

	def validate_pan(self):
		if not self.pan:
			return
		self.pan = self.pan.strip().upper()
		if not PAN_FORMAT.match(self.pan):
			frappe.throw(_("PAN must be 5 letters, 4 digits and 1 letter"))  # the value is never echoed

	def validate_bank_account(self):
		if not self.bank_account:
			return
		if not self.supplier:
			frappe.throw(_("Link or create the Supplier before choosing a Bank Account"))
		party = frappe.db.get_value("Bank Account", self.bank_account, ["party_type", "party"], as_dict=True)
		if party and (party.party_type, party.party) != ("Supplier", self.supplier):
			frappe.throw(_("Bank Account {0} does not belong to Supplier {1}").format(self.bank_account, self.supplier))

	@frappe.whitelist()
	def create_supplier(self):
		"""Create the Supplier this member is paid through and link it. The caller needs Supplier create rights."""
		self.check_permission("write")
		if self.supplier:
			frappe.throw(_("{0} is already linked to Supplier {1}").format(self.member_name, self.supplier))
		frappe.has_permission("Supplier", "create", throw=True)
		supplier = frappe.new_doc("Supplier")
		supplier.supplier_name = self.member_name
		supplier.supplier_type = "Individual"
		supplier.supplier_group = frappe.db.get_single_value("Buying Settings", "supplier_group") or frappe.db.get_value(
			"Supplier Group", {"is_group": 0}
		)
		if self.pan and supplier.meta.has_field("pan"):
			supplier.pan = self.pan
		supplier.insert()
		self.db_set("supplier", supplier.name)
		return supplier.name
