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
database) and is left out; so re-exporting a period gives only what PFMS has not taken.

ERPNext can rewrite a payment after it was exported: an advance reconciled to an invoice gets a new reference row, a
reference may point back to an advance (advance_voucher_no), and a cancelled voucher is amended under a new name. So
exports are also tracked per payment (`payment_key`: the voucher, or the advance it allocates, followed back through
amended_from to the first version). Once a payment has a live exported row in any sanction's batch, only a line
exported as such, for the same amount, counts as exported; any other line of it (changed, new, moved to another
sanction, or left after a line was removed) is excluded for review, never exported automatically. One exception: a
line of a sanction none of whose batches has the payment, while every exported line of it elsewhere is unchanged, is
exported (a payment of two sanctions' invoices goes once in each). A voucher with live exported rows can't be
cancelled (`refuse_exported_cancel`) until PFMS reports them failed or their batch is cancelled."""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.query_builder.functions import Sum
from frappe.utils import flt

VENDOR_CODE_FIELD = "oc_pfms_vendor_code"
PFMS_AGENCY_FIELD = "oc_pfms_agency"
EXPORT_TYPES = ("Expenditure", "Advance", "Transfer")
DEFAULT_LAYOUTS = {export_type: f"PFMS EAT {export_type} (placeholder)" for export_type in EXPORT_TYPES}
STATUS_REFERENCE_HEADER = "Unique Reference"  # the placeholder export's Row Reference header
PLACEHOLDER_COLUMNS = (
	(STATUS_REFERENCE_HEADER, "Row Reference"), ("Agency Unique Code", "Agency Unique Code"),
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
		payments = self.payments()
		exported = self.exported_rows(payments)
		rows, already_exported = [], 0
		for payment in (p for p in payments if p.export_type == self.export_type):
			history = exported.get(payment.payment_key)
			if history and self.exported_as_is(payment, history):
				already_exported += 1
				continue
			reason = (history and self.held_for_review(payment, history)) or payment.get("reason") or self.vendor_problem(payment)
			if reason:
				self.exclude(payment, reason)
			else:
				rows.append(payment)
		return frappe._dict(rows=rows, exclusions=self.exclusions, already_exported=already_exported)

	# payments
	def payments(self):
		payments = self.allocated() + self.unallocated() + self.paid_invoices()
		self.suppliers = supplier_details({p.supplier for p in payments})
		roots = first_versions(payments)
		for payment in payments:
			payment.export_key = export_key(payment.voucher_type, payment.voucher_no, payment.reference_doctype, payment.reference_name)
			payment.payment_key = payment_key(*roots[payment_voucher(payment)])
			if self.suppliers.get(payment.supplier, {}).get("agency"):
				payment.export_type = "Transfer"
		return sorted(payments, key=lambda p: (str(p.posting_date), p.voucher_no, p.reference_name or ""))

	def allocated(self):
		pe, ref = frappe.qb.DocType("Payment Entry"), frappe.qb.DocType("Payment Entry Reference")
		lines = self.read(
			self.payment_query(pe).join(ref).on(ref.parent == pe.name)
			.select(
				ref.reference_doctype, ref.reference_name, ref.allocated_amount.as_("amount"),
				ref.advance_voucher_type, ref.advance_voucher_no,
			)
			.where(
				(ref.parenttype == "Payment Entry") & ref.reference_doctype.isin(["Purchase Invoice", "Purchase Order"])
				& (ref.allocated_amount > 0)
			)
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
		payments = self.read(
			self.payment_query(pe)
			.select(pe.unallocated_amount.as_("amount"), pe.project, pe.cost_center)
			.where((pe.unallocated_amount > 0) & ((pe.project == self.sanction.project) | (pe.cost_center == self.sanction.cost_center)))
		)  # fmt: skip
		for payment in payments:
			payment.update(voucher_type="Payment Entry", export_type="Advance", reason=self.other_sanction(payment))
		return payments

	def other_sanction(self, payment):
		"""Why an unallocated payment with this sanction's project or cost centre can't be told apart: the other one
		belongs to another sanction."""
		other = None
		if payment.project and payment.project != self.sanction.project:
			other = frappe.db.get_value("Sanction", {"project": payment.project, "docstatus": 1})
		if not other and payment.cost_center and payment.cost_center != self.sanction.cost_center:
			other = frappe.db.get_value("Sanction", {"cost_center": payment.cost_center, "docstatus": 1})
		if other:
			return _("Payment Entry {0} names the project or cost centre of Sanction {1} as well as of Sanction {2}; correct it.").format(
				payment.voucher_no, other, self.sanction.name
			)
		return None

	def paid_invoices(self):
		pi = frappe.qb.DocType("Purchase Invoice")
		invoices = self.read(
			frappe.qb.from_(pi)
			.select(pi.name.as_("voucher_no"), pi.posting_date, pi.supplier, pi.paid_amount.as_("amount"))
			.where(
				(pi.docstatus == 1) & (pi.is_paid == 1) & (pi.is_return == 0) & (pi.company == self.sanction.company)
				& (pi.paid_amount > 0) & pi.posting_date[self.from_date : self.to_date]
			)
		)  # fmt: skip
		shares = self.on_sanction("Purchase Invoice", {invoice.voucher_no for invoice in invoices})
		payments = []
		for invoice in invoices:
			if invoice.voucher_no in shares:
				invoice.update(voucher_type="Purchase Invoice", export_type="Expenditure", party_bank_account=None, **shares[invoice.voucher_no])
				payments.append(invoice)
		return payments

	def read(self, query):
		"""Under the sanction lock, the vouchers are read with a locking read: a cancel in flight finishes (or waits)
		first, so its docstatus is the one read here."""
		return (query.for_update() if self.lock else query).run(as_dict=True)

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

	# already exported
	@staticmethod
	def exported_as_is(payment, history):
		"""The line itself is live in a batch, for the amount it has now."""
		return any(row.export_key == payment.export_key and flt(row.amount, 2) == flt(payment.amount, 2) for row in history)

	def held_for_review(self, payment, history):
		"""Why a line of a payment with live exported rows (`history`) is not exported automatically, or None for a line
		of a sanction no batch of which has the payment, while every exported line of it is unchanged."""
		exported_here = any(row.sanction == self.sanction.name for row in history)
		line_exported = any(row.export_key == payment.export_key for row in history)  # for another amount
		if not exported_here and not line_exported and self.unchanged(history):
			return None
		batches = ", ".join(sorted({row.batch for row in history}))
		return _(
			"{0} {1}: its payment is already exported to PFMS in {2}, and this line ({3}) is new or has changed since. "
			"It is excluded for review: check it against the exported rows; it is never exported automatically."
		).format(_(payment.voucher_type), payment.voucher_no, batches, frappe.format(flt(payment.amount, 2), "Currency"))

	def exported_rows(self, payments):
		"""{payment_key: [live (exported, not failed) rows of any sanction's batch]} of the payments' lines: by the
		payment's key, or by a line's export key (rows exported before payment keys were stored have none)."""
		keys = {p.payment_key for p in payments}
		by_export_key = {p.export_key: p.payment_key for p in payments}
		if not keys:
			return {}
		row, batch = frappe.qb.DocType("PFMS Export Batch Row"), frappe.qb.DocType("PFMS Export Batch")
		rows = self.read(
			frappe.qb.from_(row).join(batch).on(batch.name == row.parent)
			.select(
				row.export_key, row.payment_key, row.amount, row.voucher_type, row.voucher_no, row.reference_doctype,
				row.reference_name, row.parent.as_("batch"), batch.sanction,
			)
			.where(
				row.export_key.isnotnull() & (row.parenttype == "PFMS Export Batch")
				& (row.payment_key.isin(list(keys)) | row.export_key.isin(list(by_export_key)))
			)
		)  # fmt: skip
		history = {}
		for exported in rows:
			key = exported.payment_key if exported.payment_key in keys else by_export_key[exported.export_key]
			history.setdefault(key, []).append(exported)
		return history

	def unchanged(self, rows):
		"""Every exported row is still a line of its voucher, for the amount exported."""
		current = self.current_amounts(rows)
		return all(current.get(row.export_key) == flt(row.amount, 2) for row in rows)

	def current_amounts(self, rows):
		"""{export_key: what the exported rows' lines amount to now} (submitted vouchers only)."""
		vouchers = {(row.voucher_type, row.voucher_no) for row in rows}
		entries = [name for doctype, name in vouchers if doctype == "Payment Entry"]
		invoices = [name for doctype, name in vouchers if doctype == "Purchase Invoice"]
		amounts = {}
		if entries:
			pe, ref = frappe.qb.DocType("Payment Entry"), frappe.qb.DocType("Payment Entry Reference")
			for line in self.read(
				frappe.qb.from_(ref).join(pe).on(pe.name == ref.parent)
				.select(ref.parent, ref.reference_doctype, ref.reference_name, Sum(ref.allocated_amount).as_("amount"))
				.where((pe.docstatus == 1) & (ref.parenttype == "Payment Entry") & pe.name.isin(entries))
				.groupby(ref.parent, ref.reference_doctype, ref.reference_name)
			):  # fmt: skip
				amounts[export_key("Payment Entry", line.parent, line.reference_doctype, line.reference_name)] = flt(line.amount, 2)
			for entry in self.read(
				frappe.qb.from_(pe).select(pe.name, pe.unallocated_amount)
				.where((pe.docstatus == 1) & pe.name.isin(entries) & (pe.unallocated_amount > 0))
			):  # fmt: skip
				amounts[export_key("Payment Entry", entry.name)] = flt(entry.unallocated_amount, 2)
		if invoices:
			pi = frappe.qb.DocType("Purchase Invoice")
			for invoice in self.read(
				frappe.qb.from_(pi).select(pi.name, pi.paid_amount)
				.where((pi.docstatus == 1) & (pi.is_paid == 1) & pi.name.isin(invoices))
			):  # fmt: skip
				amounts[export_key("Purchase Invoice", invoice.name)] = flt(invoice.paid_amount, 2)
		return amounts

	def exclude(self, payment, reason):
		self.exclusions.append(
			{
				"voucher_type": payment.voucher_type, "voucher_no": payment.voucher_no,
				"reference_doctype": payment.reference_doctype, "reference_name": payment.reference_name,
				"supplier": payment.supplier, "amount": flt(payment.amount, 2), "reason": reason,
			}  # fmt: skip
		)


def payment_key(voucher_type, voucher_no):
	return f"{voucher_type}|{voucher_no}"


def payment_voucher(payment):
	"""The voucher whose money a line is: the advance it allocates, else its own voucher."""
	if payment.get("advance_voucher_no"):
		return (payment.advance_voucher_type or "Payment Entry", payment.advance_voucher_no)
	return (payment.voucher_type, payment.voucher_no)


def first_versions(payments):
	"""{(doctype, name): (doctype, first version)} following amended_from back."""
	vouchers = {payment_voucher(p) for p in payments}
	roots = {voucher: voucher for voucher in vouchers}
	for doctype in {doctype for doctype, _name in vouchers}:
		names = [name for kind, name in vouchers if kind == doctype]
		amended = dict(frappe.get_all(doctype, {"name": ["in", names], "amended_from": ["is", "set"]}, ["name", "amended_from"], as_list=True))
		for name, earlier in amended.items():
			first, seen = earlier, {name}
			while first not in seen:  # rare: walk the rest of the chain one version at a time
				seen.add(first)
				first = frappe.db.get_value(doctype, first, "amended_from") or first
			roots[(doctype, name)] = (doctype, first)
	return roots


def refuse_exported_cancel(doc, method=None):
	"""Doc event (Payment Entry / Purchase Invoice before_cancel): a voucher PFMS has, or may have, paid is withdrawn
	from PFMS first (its rows reported failed, or its batch cancelled)."""
	row = frappe.qb.DocType("PFMS Export Batch Row")
	first = first_versions([frappe._dict(voucher_type=doc.doctype, voucher_no=doc.name)])[(doc.doctype, doc.name)]
	batches = (
		frappe.qb.from_(row).select(row.parent)
		.where(
			row.export_key.isnotnull()
			& (
				((row.voucher_type == doc.doctype) & (row.voucher_no == doc.name))
				| ((row.reference_doctype == doc.doctype) & (row.reference_name == doc.name))
				| (row.payment_key == payment_key(*first))  # an amendment of an exported voucher
			)
		)
		.for_update().run(pluck=True)
	)  # fmt: skip
	if batches:
		frappe.throw(
			_("{0} {1} is exported to PFMS in {2}. Withdraw it from PFMS first: import its failed status or cancel the batch.").format(
				_(doc.doctype), doc.name, ", ".join(sorted(set(batches)))
			)
		)


def allow_withdrawn_cancel(doc, method=None):
	"""Doc event (Payment Entry / Purchase Invoice on_cancel, after ERPNext's own, which sets the ignore list): the
	batches still list a voucher whose rows PFMS failed or whose batch was cancelled (refuse_exported_cancel refused
	any other); they keep it as history and don't block the cancel."""
	doc.ignore_linked_doctypes = (*(doc.get("ignore_linked_doctypes") or ()), "PFMS Export Batch")


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
			fix_status_reference_column(name)
			continue
		frappe.get_doc(
			{
				"doctype": "PFMS Export Layout", "layout_name": name, "export_type": export_type, "is_placeholder": 1,
				"status_reference_column": STATUS_REFERENCE_HEADER,
				"columns": [{"column_header": header, "source": source} for header, source in PLACEHOLDER_COLUMNS],
			}  # fmt: skip
		).insert(ignore_permissions=True)


def fix_status_reference_column(name):
	"""Placeholder layouts seeded before P3-T18 fix 1 read the status file's references from a "Row Reference" column
	the export never wrote; point them at the export's own reference header unless they were edited."""
	layout = frappe.db.get_value("PFMS Export Layout", name, ["is_placeholder", "status_reference_column"], as_dict=True)
	if layout.is_placeholder and layout.status_reference_column == "Row Reference":
		frappe.db.set_value("PFMS Export Layout", name, "status_reference_column", STATUS_REFERENCE_HEADER)


def default_layout(export_type):
	name = DEFAULT_LAYOUTS.get(export_type)
	if name and frappe.db.exists("PFMS Export Layout", name):
		return name
	return frappe.db.get_value("PFMS Export Layout", {"export_type": export_type}, "name", order_by="creation asc")
