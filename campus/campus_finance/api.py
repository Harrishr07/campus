"""M09 Campus Finance API: the surface other modules call (`campus.campus_finance.api`)."""

import frappe

from campus.campus_finance import bank_import, fee_heads, fines, invoices, ledger


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
student_invoices = ledger.student_invoices
raise_fee_invoice = invoices.raise_fee_invoice
