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
INVOICE_FIELDS = [
	"name",
	"company",
	"posting_date",
	"due_date",
	"currency",
	"grand_total",
	"outstanding_amount",
	"status",
	"is_return",
]


def student_invoices(student, outstanding_only=False):
	"""Submitted Sales Invoices and credit notes of the student, newest first.

	An invoice is the student's when its `student` field says so (what PORTAL_SCOPES scope on); one with no
	`student` is the student's when it is made out to the student's Customer.
	"""
	customer = frappe.db.get_value("Student", student, "customer")
	filters = {"docstatus": 1}
	if outstanding_only:
		filters["outstanding_amount"] = ["!=", 0]
	invoices = frappe.get_all("Sales Invoice", {**filters, "student": student}, INVOICE_FIELDS, limit=0)
	if customer:
		invoices += frappe.get_all(
			"Sales Invoice",
			{**filters, "customer": customer, "student": ["in", ["", None]]},
			INVOICE_FIELDS,
			limit=0,
		)
	return sorted(invoices, key=lambda i: (i.posting_date, i.name), reverse=True)


def head_types():
	"""{Fee Category name or Item code: fee head type}."""
	heads = {}
	for row in frappe.get_all("Fee Category", fields=["name", "item", "oc_fee_head_type"], limit=0):
		for key in (row.name, row.item):
			if key and row.oc_fee_head_type:
				heads[key] = row.oc_fee_head_type
	return heads


def line_amounts(invoices):
	"""{invoice: {head: net amount of its lines}}."""
	lines = frappe.get_all(
		"Sales Invoice Item", {"parent": ["in", invoices or [""]], "parenttype": "Sales Invoice"},
		["parent", "item_code", "net_amount"], order_by="parent, idx", limit=0,
	)  # fmt: skip
	heads, amounts = head_types(), {}
	for line in lines:
		by_head = amounts.setdefault(line.parent, {})
		head = heads.get(line.item_code, OTHER)
		by_head[head] = by_head.get(head, 0) + flt(line.net_amount)
	return amounts


def head_shares(invoices):
	"""{invoice: [(head, share)]} with the shares of an invoice adding up to 1."""
	amounts, shares = line_amounts(invoices), {}
	for invoice in invoices:
		by_head = amounts.get(invoice) or {OTHER: 0}
		total = sum(by_head.values())
		shares[invoice] = [
			(head, amount / total if total else 1 / len(by_head)) for head, amount in by_head.items()
		]
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
	"""[(company, head, outstanding)] of the student's open invoices, optionally of `companies` only.

	A credit note reducing its original invoice is attributed to the heads of its own lines; what else has
	reduced the invoice (payments) is spread over the heads pro rata. A credit note that carries its own
	outstanding is an invoice of its own, split over its own lines.
	"""
	invoices = [
		i
		for i in student_invoices(student, outstanding_only=True)
		if companies is None or i.company in companies
	]
	notes = credit_notes_against([i.name for i in invoices])
	shares = head_shares([i.name for i in invoices] + [n.name for n in notes])
	lines = []
	for invoice in invoices:
		heads = head_amounts(invoice, [n for n in notes if n.return_against == invoice.name], shares)
		lines += [(invoice.company, head, amount) for head, amount in heads]
	return lines


def credit_notes_against(invoices):
	"""Submitted credit notes that reduce the outstanding amount of those invoices."""
	return frappe.get_all(
		"Sales Invoice",
		{"return_against": ["in", invoices or [""]], "docstatus": 1, "is_return": 1, "update_outstanding_for_self": 0},
		["name", "return_against", "grand_total"], limit=0,
	)  # fmt: skip


def head_amounts(invoice, notes, shares):
	"""[(head, outstanding)] of an invoice: its heads, less its credit notes' own heads, less payments pro rata."""
	by_head = {}
	for head, amount in split(invoice.grand_total, shares[invoice.name]):
		by_head[head] = by_head.get(head, 0) + amount
	for note in notes:
		for head, amount in split(note.grand_total, shares[note.name]):
			by_head[head] = by_head.get(head, 0) + amount
	remaining = sum(by_head.values())
	if not remaining:
		return []
	settled = flt(remaining - invoice.outstanding_amount, 2)  # paid, written off or otherwise settled
	heads = list(by_head.items())
	return split_remainder(invoice.outstanding_amount, heads, settled, remaining)


def split_remainder(outstanding, heads, settled, remaining):
	"""Take `settled` off the heads pro rata to what each holds; the last head absorbs the rounding."""
	parts, left = [], flt(outstanding, 2)
	for head, amount in heads[:-1]:
		part = flt(amount - settled * amount / remaining, 2)
		parts.append((head, part))
		left -= part
	return [*parts, (heads[-1][0], flt(left, 2))]


def has_dues(student, scopes=None, companies=None):
	"""{total, by_company, by_head, blocking} of what the student owes.

	`scopes` limits it to those fee head types (e.g. ["Exam"]); `companies` to those companies (all when None).
	`total` nets credit balances against dues; `blocking` does not: it is the sum of the positive balances per
	company and head, so a refund owed by one company never hides a due of another. Gate on `blocking`.
	Zero entries are left out of the breakdowns.
	"""
	dues = frappe._dict(total=0, by_company={}, by_head={}, blocking=0)
	cells = {}
	for company, head, amount in outstanding_lines(student, companies):
		if scopes and head not in scopes:
			continue
		dues.total += amount
		dues.by_company[company] = dues.by_company.get(company, 0) + amount
		dues.by_head[head] = dues.by_head.get(head, 0) + amount
		cells[company, head] = cells.get((company, head), 0) + amount
	dues.total = flt(dues.total, 2)
	dues.blocking = flt(sum(amount for amount in cells.values() if flt(amount, 2) > 0), 2)
	dues.by_company = {k: flt(v, 2) for k, v in sorted(dues.by_company.items()) if flt(v, 2)}
	dues.by_head = {k: flt(v, 2) for k, v in sorted(dues.by_head.items()) if flt(v, 2)}
	return dues


def ledger_rows(student, companies=None):
	"""Ledger postings of the student, oldest first, with a running balance.

	The student's invoices are matched as in `student_invoices`; payments and journals are those posted to the
	student's Customer. Invoices and credit notes are listed once per fee head, the others as one row with no head.
	"""
	own = {i.name for i in student_invoices(student)}
	entries = [
		e
		for e in party_entries(student, own, companies)
		if e.voucher_type != "Sales Invoice" or e.voucher_no in own
	]
	shares = head_shares(sorted(own))
	currencies, rows, balance = {}, [], 0
	for entry in sorted(entries, key=lambda e: (e.posting_date, e.creation)):
		currency = currencies.setdefault(
			entry.company, frappe.get_cached_value("Company", entry.company, "default_currency")
		)
		for head, debit, credit in entry_parts(entry, shares):
			if not (debit or credit):
				continue
			balance += debit - credit
			rows.append(
				{
					"posting_date": entry.posting_date,
					"company": entry.company,
					"head": head,
					"currency": currency,
					"voucher_type": entry.voucher_type,
					"voucher_no": entry.voucher_no,
					"debit": debit,
					"credit": credit,
					"balance": flt(balance, 2),
				}
			)
	return rows


def party_entries(student, invoices, companies):
	"""Customer GL entries of the student's Customer and of the student's invoices, optionally of `companies` only."""
	customer = frappe.db.get_value("Student", student, "customer")
	base = {"party_type": "Customer", "is_cancelled": 0}
	if companies is not None:
		base["company"] = ["in", companies or [""]]
	fields = ["name", "creation", "posting_date", "company", "voucher_type", "voucher_no", "debit", "credit"]
	entries = frappe.get_all("GL Entry", {**base, "party": customer}, fields, limit=0) if customer else []
	if invoices:
		entries += frappe.get_all(
			"GL Entry",
			{**base, "voucher_type": "Sales Invoice", "voucher_no": ["in", sorted(invoices)]},
			fields,
			limit=0,
		)
	return list({e.name: e for e in entries}.values())


def entry_parts(entry, shares):
	"""[(head, debit, credit)] of one GL entry: split over heads for an invoice, whole otherwise."""
	if entry.voucher_type != "Sales Invoice":
		return [("", flt(entry.debit), flt(entry.credit))]
	debits, credits = (
		split(entry.debit, shares[entry.voucher_no]),
		split(entry.credit, shares[entry.voucher_no]),
	)
	return [(head, debit, credit) for (head, debit), (_head, credit) in zip(debits, credits, strict=True)]
