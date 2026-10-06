"""M09-04 Student fee ledger and dues: one source for the ledger report, the dues gate and the student portal.

A student's fees are the submitted Sales Invoices (and credit notes) of the student's Customer in any
company: the college invoices tuition, the trust invoices hostel or transport to the same Customer. What a
student still owes is the outstanding amount of those invoices, which payments and credit notes reduce
(an advance not yet allocated to an invoice does not). The fee head of an invoice line is the fee head
type of its item's Fee Category, anything else being "Other"; an invoice's outstanding amount and its ledger
postings are split over its heads in proportion to the line amounts.
"""

import frappe
from frappe.utils import flt

OTHER = "Other"
INVOICE_FIELDS = ["name", "company", "posting_date", "due_date", "currency", "grand_total", "outstanding_amount", "status", "is_return"]


def student_invoices(student, outstanding_only=False):
	"""Submitted Sales Invoices and credit notes of the student (their `student` field or their Customer), newest first."""
	customer = frappe.db.get_value("Student", student, "customer")
	filters = {"docstatus": 1}
	if outstanding_only:
		filters["outstanding_amount"] = ["!=", 0]
	or_filters = {"student": student, **({"customer": customer} if customer else {})}
	return frappe.get_all(
		"Sales Invoice", filters, INVOICE_FIELDS, or_filters=or_filters, order_by="posting_date desc, name desc", limit=0
	)


def head_types():
	"""{Fee Category name or Item code: fee head type}."""
	heads = {}
	for row in frappe.get_all("Fee Category", fields=["name", "item", "oc_fee_head_type"], limit=0):
		for key in (row.name, row.item):
			if key and row.oc_fee_head_type:
				heads[key] = row.oc_fee_head_type
	return heads


def head_shares(invoices):
	"""{invoice: [(head, share)]} with the shares of an invoice adding up to 1."""
	lines = frappe.get_all(
		"Sales Invoice Item", {"parent": ["in", invoices or [""]], "parenttype": "Sales Invoice"},
		["parent", "item_code", "net_amount"], order_by="parent, idx", limit=0,
	)  # fmt: skip
	heads, amounts = head_types(), {}
	for line in lines:
		by_head = amounts.setdefault(line.parent, {})
		head = heads.get(line.item_code, OTHER)
		by_head[head] = by_head.get(head, 0) + flt(line.net_amount)
	shares = {}
	for invoice in invoices:
		by_head = amounts.get(invoice) or {OTHER: 0}
		total = sum(by_head.values())
		shares[invoice] = [(head, amount / total if total else 1 / len(by_head)) for head, amount in by_head.items()]
	return shares


def split(amount, shares):
	"""[(head, part)] of `amount` by `shares`, the last head taking the rounding remainder."""
	parts, remaining = [], flt(amount, 2)
	for head, share in shares[:-1]:
		part = flt(amount * share, 2)
		parts.append((head, part))
		remaining -= part
	return [*parts, (shares[-1][0], flt(remaining, 2))]


def outstanding_lines(student, companies=None):
	"""[(company, head, outstanding)] of the student's open invoices, optionally of `companies` only."""
	invoices = [i for i in student_invoices(student, outstanding_only=True) if companies is None or i.company in companies]
	shares = head_shares([i.name for i in invoices])
	return [
		(invoice.company, head, part)
		for invoice in invoices
		for head, part in split(invoice.outstanding_amount, shares[invoice.name])
	]


def has_dues(student, scopes=None, companies=None):
	"""{total, by_company, by_head} of what the student owes.

	`scopes` limits it to those fee head types (e.g. ["Exam"]); `companies` to those companies (all when None).
	A credit balance is netted against the other dues. Zero totals are left out of the breakdowns.
	"""
	dues = frappe._dict(total=0, by_company={}, by_head={})
	for company, head, amount in outstanding_lines(student, companies):
		if scopes and head not in scopes:
			continue
		dues.total += amount
		dues.by_company[company] = dues.by_company.get(company, 0) + amount
		dues.by_head[head] = dues.by_head.get(head, 0) + amount
	dues.total = flt(dues.total, 2)
	dues.by_company = {k: flt(v, 2) for k, v in sorted(dues.by_company.items()) if flt(v, 2)}
	dues.by_head = {k: flt(v, 2) for k, v in sorted(dues.by_head.items()) if flt(v, 2)}
	return dues


def ledger_rows(student, companies=None):
	"""Ledger postings of the student's Customer, oldest first, with a running balance.

	Invoices and credit notes are listed once per fee head; payments and journals as one row with no head.
	"""
	customer = frappe.db.get_value("Student", student, "customer")
	if not customer:
		return []
	filters = {"party_type": "Customer", "party": customer, "is_cancelled": 0}
	if companies is not None:
		filters["company"] = ["in", companies or [""]]
	entries = frappe.get_all(
		"GL Entry", filters, ["posting_date", "company", "voucher_type", "voucher_no", "debit", "credit"],
		order_by="posting_date, creation", limit=0,
	)  # fmt: skip
	invoices = {e.voucher_no for e in entries if e.voucher_type == "Sales Invoice"}
	shares = head_shares(sorted(invoices))
	rows, balance = [], 0
	for entry in entries:
		for head, debit, credit in entry_parts(entry, shares):
			if not (debit or credit):
				continue
			balance += debit - credit
			rows.append(
				{
					"posting_date": entry.posting_date, "company": entry.company, "head": head,
					"voucher_type": entry.voucher_type, "voucher_no": entry.voucher_no, "debit": debit, "credit": credit, "balance": flt(balance, 2),
				}
			)
	return rows


def entry_parts(entry, shares):
	"""[(head, debit, credit)] of one GL entry: split over heads for an invoice, whole otherwise."""
	if entry.voucher_type != "Sales Invoice":
		return [("", flt(entry.debit), flt(entry.credit))]
	debits, credits = split(entry.debit, shares[entry.voucher_no]), split(entry.credit, shares[entry.voucher_no])
	return [(head, debit, credit) for (head, debit), (_head, credit) in zip(debits, credits, strict=True)]
