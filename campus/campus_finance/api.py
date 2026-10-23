"""M09 Campus Finance API: the surface other modules call (`campus.campus_finance.api`)."""

import frappe

from campus.campus_finance import (
	bank_import,
	fee_heads,
	fines,
	gateways,
	invoices,
	ledger,
	numbering,
	refunds,
	scholarships,
)


def fee_structure_for(program, academic_year, quota, category, company):
	"""The submitted Fee Structure that applies to a program, year, quota and student category, or None.

	A structure naming the quota or category beats one leaving it blank (quota first, then category);
	blank ones are the fallback for every quota or category. Among equals the latest wins.
	"""
	structures = frappe.get_all(
		"Fee Structure",
		{"docstatus": 1, "program": program, "academic_year": academic_year, "company": company},
		["name", "oc_admission_quota", "student_category"],
		order_by="creation desc",
		limit=0,
	)
	fits = [
		s for s in structures
		if s.oc_admission_quota in (quota, None, "") and s.student_category in (category, None, "")
	]  # fmt: skip
	best = max(fits, key=lambda s: (bool(s.oc_admission_quota), bool(s.student_category)), default=None)
	return best and best.name


set_item_default = fee_heads.set_item_default
daily_fine_run = fines.daily_fine_run
import_bank_collections = bank_import.start_import
has_dues = ledger.has_dues
head_types = ledger.head_types
CAUTION_DEPOSIT = fee_heads.CAUTION_DEPOSIT
student_invoices = ledger.student_invoices
raise_fee_invoice = invoices.raise_fee_invoice
check_fee_invoice = invoices.check_fee_invoice
next_number = numbering.next_number
validate_number_prefix = numbering.validate_prefix
scholarship_beneficiaries = scholarships.scholarship_beneficiaries
disburse_scholarship = scholarships.disburse
make_credit_note = refunds.make_credit_note
paid_by_student = refunds.paid_by_student
scholarship_vouchers = refunds.scholarship_vouchers
make_refund_payment = refunds.make_refund_payment
unallocated_advance = refunds.unallocated_advance
make_advance_refund = refunds.make_advance_refund
fee_payment_link = gateways.fee_payment_link


def can_pay_online(company):
	"""Whether `company` has a default Payment Gateway Account with a supported gateway (never throws)."""
	if not frappe.db.table_exists("Payment Gateway Account"):  # the payments app is not installed
		return False
	account = frappe.db.get_value("Payment Gateway Account", {"company": company, "is_default": 1}, ["payment_gateway", "payment_channel"], as_dict=True)
	return bool(account and account.payment_channel != "Phone" and account.payment_gateway in gateways.ADAPTERS)
