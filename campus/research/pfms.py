"""M08-07 PFMS EAT export: which payments of a sanction go into a PFMS Export Batch.

A sanction's payments in a period are:
- Payment Entries (Pay, to a Supplier) allocated to its Purchase Invoices: expenditure;
- Purchase Invoices paid on the invoice itself (is_paid): expenditure;
- Payment Entries allocated to its Purchase Orders, or left unallocated on its project or cost centre: advance;
- any of these to a Supplier marked as a registered PFMS agency (`oc_pfms_agency`): transfer.
An invoice or order is the sanction's when all its lines are on the sanction's cost centre; one only partly on it is
excluded and reported (its share can't be told from the payment).

The vendor check excludes and reports a payment to a Supplier without a PFMS vendor code (`oc_pfms_vendor_code`) or
without a bank account carrying an account number and IFSC (the payment's party bank account, else the Supplier's
default). A payment already in a submitted batch, and not reported failed by PFMS, holds its export key (unique in the
database) and is left out; so re-exporting a period gives only what PFMS has not taken."""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt

VENDOR_CODE_FIELD = "oc_pfms_vendor_code"
PFMS_AGENCY_FIELD = "oc_pfms_agency"
EXPORT_TYPES = ("Expenditure", "Advance", "Transfer")
DEFAULT_LAYOUTS = {export_type: f"PFMS EAT {export_type} (placeholder)" for export_type in EXPORT_TYPES}
PLACEHOLDER_COLUMNS = (
	("Unique Reference", "Row Reference"), ("Agency Unique Code", "Agency Unique Code"),
	("Sanction Order No", "Sanction Order No"), ("Payment Date", "Payment Date"), ("Vendor Code", "PFMS Vendor Code"),
	("Vendor Name", "Vendor Name"), ("Account Number", "Bank Account No"), ("IFSC", "IFSC"), ("Amount", "Amount"),
	("Component", "Budget Head"), ("Voucher No", "Voucher No"), ("Bill No", "Invoice or Order No"),
)  # fmt: skip


def export_key(voucher_type, voucher_no, reference_doctype=None, reference_name=None):
	"""What makes a payment row one PFMS payment: the voucher and the invoice or order it pays."""
	return "|".join((voucher_type, voucher_no, reference_doctype or "", reference_name or ""))


class PaymentSelection:
	"""The rows, exclusions and already-exported count of `export_type` for a sanction (a dict of Sanction fields)
	and period. With `lock`, the exported keys are read with a locking read (call it under the sanction lock)."""

	def __init__(self, sanction, export_type, from_date, to_date, lock=False):
		self.sanction, self.export_type, self.lock = sanction, export_type, lock
		self.from_date, self.to_date = from_date, to_date
		self.exclusions = []

	def run(self):
		payments = [p for p in self.payments() if p.export_type == self.export_type]
		exported = self.exported_keys([p.export_key for p in payments])
		rows = []
		for payment in payments:
			if payment.export_key in exported:
				continue
			reason = payment.get("reason") or self.vendor_problem(payment)
			if reason:
				self.exclude(payment, reason)
			else:
				rows.append(payment)
		return frappe._dict(rows=rows, exclusions=self.exclusions, already_exported=len(exported))

	# payments
	def payments(self):
		payments = self.allocated() + self.unallocated() + self.paid_invoices()
		self.suppliers = supplier_details({p.supplier for p in payments})
		for payment in payments:
			payment.export_key = export_key(payment.voucher_type, payment.voucher_no, payment.reference_doctype, payment.reference_name)
			if self.suppliers.get(payment.supplier, {}).get("agency"):
				payment.export_type = "Transfer"
		return sorted(payments, key=lambda p: (str(p.posting_date), p.voucher_no, p.reference_name or ""))

	def allocated(self):
		pe, ref = frappe.qb.DocType("Payment Entry"), frappe.qb.DocType("Payment Entry Reference")
		lines = (
			self.payment_query(pe).join(ref).on(ref.parent == pe.name)
			.select(ref.reference_doctype, ref.reference_name, ref.allocated_amount.as_("amount"))
			.where(
				(ref.parenttype == "Payment Entry") & ref.reference_doctype.isin(["Purchase Invoice", "Purchase Order"])
				& (ref.allocated_amount > 0)
			)
			.run(as_dict=True)
		)  # fmt: skip
		documents = {}
		for doctype in ("Purchase Invoice", "Purchase Order"):
			documents[doctype] = self.on_sanction(doctype, {line.reference_name for line in lines if line.reference_doctype == doctype})
		payments = []
		for line in lines:
			share = documents[line.reference_doctype].get(line.reference_name)
			if share is None:
				continue
			line.voucher_type = "Payment Entry"
			line.export_type = "Expenditure" if line.reference_doctype == "Purchase Invoice" else "Advance"
			line.update(share)
			payments.append(line)
		return payments

	def unallocated(self):
		pe = frappe.qb.DocType("Payment Entry")
		payments = (
			self.payment_query(pe)
			.select(pe.unallocated_amount.as_("amount"))
			.where((pe.unallocated_amount > 0) & ((pe.project == self.sanction.project) | (pe.cost_center == self.sanction.cost_center)))
			.run(as_dict=True)
		)  # fmt: skip
		for payment in payments:
			payment.update(voucher_type="Payment Entry", export_type="Advance")
		return payments

	def paid_invoices(self):
		pi = frappe.qb.DocType("Purchase Invoice")
		invoices = (
			frappe.qb.from_(pi)
			.select(pi.name.as_("voucher_no"), pi.posting_date, pi.supplier, pi.paid_amount.as_("amount"))
			.where(
				(pi.docstatus == 1) & (pi.is_paid == 1) & (pi.is_return == 0) & (pi.company == self.sanction.company)
				& (pi.paid_amount > 0) & pi.posting_date[self.from_date : self.to_date]
			)
			.run(as_dict=True)
		)  # fmt: skip
		shares = self.on_sanction("Purchase Invoice", {invoice.voucher_no for invoice in invoices})
		payments = []
		for invoice in invoices:
			if invoice.voucher_no in shares:
				invoice.update(voucher_type="Purchase Invoice", export_type="Expenditure", party_bank_account=None, **shares[invoice.voucher_no])
				payments.append(invoice)
		return payments

	def payment_query(self, pe):
		return (
			frappe.qb.from_(pe)
			.select(
				pe.name.as_("voucher_no"), pe.posting_date, pe.party.as_("supplier"), pe.party_bank_account,
			)
			.where(
				(pe.docstatus == 1) & (pe.payment_type == "Pay") & (pe.party_type == "Supplier")
				& (pe.company == self.sanction.company) & pe.posting_date[self.from_date : self.to_date]
			)
		)  # fmt: skip

	def on_sanction(self, doctype, names):
		"""{name: {budget_head, reason}} of the documents with lines on the sanction's cost centre; `reason` is set when
		only some of a document's lines are."""
		if not names:
			return {}
		item = frappe.qb.DocType(f"{doctype} Item")
		lines = (
			frappe.qb.from_(item).select(item.parent, item.cost_center, item.oc_budget_head)
			.where((item.parenttype == doctype) & item.parent.isin(list(names)))
			.run(as_dict=True)
		)  # fmt: skip
		by_document = {}
		for line in lines:
			by_document.setdefault(line.parent, []).append(line)
		shares = {}
		for name, document_lines in by_document.items():
			ours = [line for line in document_lines if line.cost_center == self.sanction.cost_center]
			if not ours:
				continue
			heads = sorted({line.oc_budget_head for line in ours if line.oc_budget_head})
			reason = None
			if len(ours) != len(document_lines):
				reason = _("{0} {1} is only partly on Sanction {2}'s cost centre.").format(_(doctype), name, self.sanction.name)
			shares[name] = {"budget_head": ", ".join(heads), "reason": reason}
		return shares

	# checks
	def vendor_problem(self, payment):
		supplier = self.suppliers.get(payment.supplier) or {}
		problems = []
		if not supplier.get("vendor_code"):
			problems.append(_("Supplier {0} has no PFMS vendor code.").format(payment.supplier))
		bank = bank_details(payment.supplier, payment.party_bank_account or supplier.get("default_bank_account"))
		if bank:
			payment.update(bank)
		else:
			problems.append(_("Supplier {0} has no bank account with an account number and IFSC.").format(payment.supplier))
		payment.update(supplier_name=supplier.get("supplier_name"), pfms_vendor_code=supplier.get("vendor_code"))
		return " ".join(problems)

	def exported_keys(self, keys):
		if not keys:
			return set()
		row = frappe.qb.DocType("PFMS Export Batch Row")
		query = frappe.qb.from_(row).select(row.export_key).where(row.export_key.isin(keys))
		return set((query.for_update() if self.lock else query).run(pluck=True))

	def exclude(self, payment, reason):
		self.exclusions.append(
			{
				"voucher_type": payment.voucher_type, "voucher_no": payment.voucher_no,
				"reference_doctype": payment.reference_doctype, "reference_name": payment.reference_name,
				"supplier": payment.supplier, "amount": flt(payment.amount, 2), "reason": reason,
			}  # fmt: skip
		)


def supplier_details(suppliers):
	if not suppliers:
		return {}
	rows = frappe.get_all(
		"Supplier",
		{"name": ["in", list(suppliers)]},
		["name", "supplier_name", "default_bank_account", f"{VENDOR_CODE_FIELD} as vendor_code", f"{PFMS_AGENCY_FIELD} as agency"],
	)
	return {row.name: row for row in rows}


def bank_details(supplier, preferred=None):
	"""{bank_account, bank_account_no, ifsc} of the supplier's usable bank account, or None."""
	fields = ["name", "bank_account_no", "branch_code", "party_type", "party", "disabled"]
	account = frappe.db.get_value("Bank Account", preferred, fields, as_dict=True) if preferred else None
	if not account or (account.party_type, account.party) != ("Supplier", supplier) or account.disabled:
		account = frappe.db.get_value(
			"Bank Account", {"party_type": "Supplier", "party": supplier, "disabled": 0}, fields, as_dict=True,
			order_by="is_default desc, creation asc",
		)  # fmt: skip
	if not account or not (account.bank_account_no or "").strip() or not (account.branch_code or "").strip():
		return None
	return {"bank_account": account.name, "bank_account_no": account.bank_account_no.strip(), "ifsc": account.branch_code.strip()}


# setup (install and migrate)
def supplier_fields():
	return {
		"Supplier": [
			{
				"fieldname": VENDOR_CODE_FIELD, "label": "PFMS Vendor Code", "fieldtype": "Data", "insert_after": "default_bank_account",
				"description": "The vendor's code in PFMS. Payments to a vendor without it are left out of PFMS exports.",
			},
			{
				"fieldname": PFMS_AGENCY_FIELD, "label": "Registered PFMS Agency", "fieldtype": "Check", "insert_after": VENDOR_CODE_FIELD,
				"description": "Payments to this supplier are fund transfers to another PFMS agency.",
			},
		]
	}  # fmt: skip


def setup_pfms_fields():
	create_custom_fields(supplier_fields(), update=True)


def seed_layouts():
	"""One placeholder layout per export type, until the official EAT file spec is supplied. Edited ones are kept."""
	for export_type, name in DEFAULT_LAYOUTS.items():
		if frappe.db.exists("PFMS Export Layout", name):
			continue
		frappe.get_doc(
			{
				"doctype": "PFMS Export Layout", "layout_name": name, "export_type": export_type, "is_placeholder": 1,
				"columns": [{"column_header": header, "source": source} for header, source in PLACEHOLDER_COLUMNS],
			}  # fmt: skip
		).insert(ignore_permissions=True)


def default_layout(export_type):
	name = DEFAULT_LAYOUTS.get(export_type)
	if name and frappe.db.exists("PFMS Export Layout", name):
		return name
	return frappe.db.get_value("PFMS Export Layout", {"export_type": export_type}, "name", order_by="creation asc")
