"""M09-04 Student Fee Ledger: invoices, credit notes and payments of a student across companies.

Limited to the companies the user is permitted for (User Permission on Company); the summary shows what is
still owed by company and by fee head.
"""

import frappe
from frappe import _

from campus.campus_finance import ledger
from campus.campus_platform.company_scope import permitted_companies


def execute(filters=None):
	filters = frappe._dict(filters or {})
	companies = visible_companies(filters.company)
	return (
		columns(),
		ledger.ledger_rows(filters.student, companies),
		None,
		None,
		summary(filters.student, companies),
	)


def visible_companies(company):
	"""The companies to show: the one asked for if permitted, else every permitted one (None: unrestricted)."""
	permitted = permitted_companies(frappe.session.user)
	if not company:
		return permitted
	if permitted is not None and company not in permitted:
		frappe.throw(
			_("You are not permitted to see the company {0}.").format(company), frappe.PermissionError
		)
	return [company]


def columns():
	return [
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "company", "label": _("Company"), "fieldtype": "Link", "options": "Company", "width": 180},
		{"fieldname": "voucher_type", "label": _("Voucher Type"), "fieldtype": "Data", "width": 120},
		{"fieldname": "voucher_no", "label": _("Voucher No"), "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 160},
		{"fieldname": "head", "label": _("Fee Head"), "fieldtype": "Data", "width": 130},
		{"fieldname": "currency", "label": _("Currency"), "fieldtype": "Link", "options": "Currency", "width": 70},
		{"fieldname": "debit", "label": _("Debit"), "fieldtype": "Currency", "options": "currency", "width": 110},
		{"fieldname": "credit", "label": _("Credit"), "fieldtype": "Currency", "options": "currency", "width": 110},
		{"fieldname": "balance", "label": _("Balance"), "fieldtype": "Currency", "options": "currency", "width": 120},
	]  # fmt: skip


def summary(student, companies):
	dues = ledger.has_dues(student, companies=companies)
	return [
		{
			"label": _("Outstanding"),
			"value": dues.blocking,
			"datatype": "Currency",
			"indicator": "Red" if dues.blocking > 0 else "Green",
		}
	] + [
		{"label": label, "value": amount, "datatype": "Currency"}
		for label, amount in (*dues.by_company.items(), *dues.by_head.items())
	]
