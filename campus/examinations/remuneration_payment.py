"""M06-04 Examiner remuneration payment: an HRMS Additional Salary on the Campus-owned component "Campus Exam
Remuneration" for internal examiners (on the next payroll), or a draft Purchase Invoice for an external examiner's
Supplier, with TDS withheld by ERPNext / india_compliance per the Supplier's Tax Withholding Category. Accounts submits
the invoice only as approved (Supplier, college, amount per Item), and the claim then takes its TDS and net figures;
the invoice of a submitted claim is cancelled by cancelling the claim (Purchase Invoice doc events). Also the seeded
component and approval policy. HRMS's own salary components are never changed."""

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from campus.examinations import remuneration_rules as rules

CLAIM = "Examiner Remuneration Claim"
SALARY_COMPONENT = "Campus Exam Remuneration"
POLICY = "Examiner Remuneration Claim Approval"


# ---- internal examiners: Additional Salary ----------------------------------------------------------------------


def post_additional_salary(claim):
	"""A submitted Additional Salary for the claim total on the employee's next payroll. Runs as the approver: every
	input comes from the server-computed claim."""
	payroll_date = rules.next_payroll_date(claim.posting_date, last_processed_slip_end(claim.employee, claim.company))
	additional = frappe.get_doc(
		{
			"doctype": "Additional Salary", "employee": claim.employee, "company": claim.company, "currency": claim.currency,
			"salary_component": SALARY_COMPONENT, "amount": claim.total_amount, "payroll_date": payroll_date,
			"overwrite_salary_structure_amount": 0, "ref_doctype": CLAIM, "ref_docname": claim.name,
		}
	)  # fmt: skip
	additional.flags.ignore_permissions = True
	additional.insert()
	additional.submit()
	return additional


def last_processed_slip_end(employee, company):
	return frappe.db.get_value("Salary Slip", {"employee": employee, "company": company, "docstatus": 1}, "end_date", order_by="end_date desc")


def cancel_additional_salary(claim):
	"""HRMS refuses while a submitted Salary Slip has paid it."""
	if claim.additional_salary and frappe.db.get_value("Additional Salary", claim.additional_salary, "docstatus") == 1:
		additional = frappe.get_doc("Additional Salary", claim.additional_salary)
		additional.flags.ignore_permissions = True
		additional.cancel()


# ---- external examiners: Purchase Invoice -----------------------------------------------------------------------


def invoice_lines(claim):
	"""{Item: amount} for the invoice; throws naming an activity whose rate has no Service Item, or an Item without
	the HSN/SAC code india_compliance requires."""
	try:
		lines = rules.amount_by_item(claim.items)
	except rules.MissingItem as missing:
		frappe.throw(_("Set the Service Item on the Remuneration Rate for {0}: external examiners are paid by Purchase Invoice.").format(_(missing.activity)))
	if frappe.get_meta("Item").has_field("gst_hsn_code"):
		for item in lines:
			if not frappe.db.get_value("Item", item, "gst_hsn_code"):
				frappe.throw(_("Item {0} (Service Item of a Remuneration Rate) has no HSN/SAC code.").format(item))
	return lines


def draft_purchase_invoice(claim):
	"""A draft Purchase Invoice for the claim's Supplier; Accounts reviews and submits it."""
	invoice = frappe.new_doc("Purchase Invoice")
	invoice.update(
		{
			"company": claim.company, "supplier": claim.supplier, "posting_date": claim.posting_date, "set_posting_time": 1,
			"bill_no": claim.name, "apply_tds": 1,
			"remarks": _("Examiner Remuneration Claim {0}: {1}, {2}").format(claim.name, claim.examiner_name, claim.exam_session),
		}
	)  # fmt: skip
	for item, amount in invoice_lines(claim).items():
		invoice.append(
			"items",
			{"item_code": item, "description": _("Examination remuneration"), "qty": 1, "rate": amount, "apply_tds": 1, "tax_withholding_category": claim.tds_section},
		)  # fmt: skip
	invoice.flags.ignore_permissions = True
	invoice.insert()
	return invoice


def payable_figures(invoice):
	withheld = sum(row.base_tax_amount for row in invoice.taxes if row.is_tax_withholding_account)
	return {"tds_amount": withheld, "net_payable": invoice.rounded_total or invoice.grand_total}


def cancel_or_delete_invoice(claim):
	"""Cancelling the claim cancels its submitted invoice (as the user, so Accounts' rights and ERPNext's payment
	checks apply) or deletes a draft one."""
	status = claim.purchase_invoice and frappe.db.get_value("Purchase Invoice", claim.purchase_invoice, "docstatus", for_update=True)
	if status == 1:
		frappe.get_doc("Purchase Invoice", claim.purchase_invoice).cancel()
	elif status == 0:
		invoice = claim.purchase_invoice
		claim.db_set("purchase_invoice", None)
		frappe.delete_doc("Purchase Invoice", invoice, ignore_permissions=True)


def refuse_cancel_after_payment(claim):
	"""A claim whose submitted invoice has any payment allocated (Payment Entry, Journal Entry, debit note: Payment
	Ledger rows against it from another voucher) is not cancelled: ERPNext would unlink the payment, leaving it an
	advance while the claim's work is freed for a second payout."""
	if not claim.purchase_invoice or frappe.db.get_value("Purchase Invoice", claim.purchase_invoice, "docstatus", for_update=True) != 1:
		return
	ledger = frappe.qb.DocType("Payment Ledger Entry")
	rows = (
		frappe.qb.from_(ledger)
		.select(ledger.voucher_no)
		.where(
			(ledger.against_voucher_type == "Purchase Invoice") & (ledger.against_voucher_no == claim.purchase_invoice)
			& (ledger.voucher_no != claim.purchase_invoice) & (ledger.delinked == 0)
		)
		.for_update()  # waits on ledger rows a concurrent payment is writing
	).run()  # fmt: skip
	vouchers = sorted({row[0] for row in rows})
	if vouchers:
		frappe.throw(
			_("Purchase Invoice {0} has payments allocated ({1}): cancel or unallocate the payment or debit note first.").format(
				claim.purchase_invoice, ", ".join(vouchers)
			)
		)


def check_paid_invoice(voucher, method=None):
	"""Payment Entry / Journal Entry before_submit: a voucher paying a claim's Purchase Invoice locks the invoice row
	(so it waits on a claim cancel in flight) and is refused unless the invoice is still submitted."""
	if voucher.doctype == "Payment Entry":
		invoices = {r.reference_name for r in voucher.references if r.reference_doctype == "Purchase Invoice"}
	else:
		invoices = {r.reference_name for r in voucher.accounts if r.reference_type == "Purchase Invoice"}
	claimed = invoices and set(frappe.get_all(CLAIM, {"purchase_invoice": ["in", list(invoices)]}, pluck="purchase_invoice"))
	for invoice in sorted(claimed or ()):
		if frappe.db.get_value("Purchase Invoice", invoice, "docstatus", for_update=True) != 1:
			frappe.throw(_("Purchase Invoice {0} is no longer submitted; it cannot be paid.").format(invoice))


def invoice_chain(invoice):
	"""The invoice and every cancelled invoice it amends, back to the first."""
	names, current = [invoice.name], invoice.amended_from
	while current and current not in names:
		names.append(current)
		current = frappe.db.get_value("Purchase Invoice", current, "amended_from")
	return names


def paid_claim(invoice):
	"""The submitted claim an invoice (or a cancelled invoice it amends) pays (locking read)."""
	return frappe.db.get_value(CLAIM, {"purchase_invoice": ["in", invoice_chain(invoice)], "docstatus": 1}, "name", for_update=True)


def check_invoice(invoice, method=None):
	"""Purchase Invoice before_submit: an invoice of a claim pays exactly the approved claim (its Supplier, college and
	amount per Item before tax, TDS applied when the Supplier has a category, no added charge besides GST); an
	amendment of an invoice whose claim was cancelled is never submitted (the claim's work is free again)."""
	name = paid_claim(invoice)
	if name:
		claim = frappe.get_doc(CLAIM, name)
		check_invoice_matches(invoice, claim)
		check_tds_and_charges(invoice, claim)
		return
	cancelled = frappe.db.get_value(CLAIM, {"purchase_invoice": ["in", invoice_chain(invoice)], "docstatus": 2}, "name")
	if cancelled:
		frappe.throw(
			_("Purchase Invoice {0} belongs to the cancelled Examiner Remuneration Claim {1}: amend the claim instead.").format(invoice.name, cancelled)
		)


def refresh_claim(invoice, method=None):
	"""Purchase Invoice on_submit: the claim takes the invoice's TDS and net figures. A submitted amendment of the
	claim's cancelled invoice becomes the claim's invoice."""
	name = paid_claim(invoice)
	if name:
		frappe.db.set_value(CLAIM, name, {"purchase_invoice": invoice.name, **payable_figures(invoice)})


def check_invoice_matches(invoice, claim):
	billed = {}
	for row in invoice.items:
		billed[row.item_code] = flt(billed.get(row.item_code, 0) + flt(row.base_net_amount), 2)
	expected = {item: flt(amount, 2) for item, amount in invoice_lines(claim).items()}
	if (invoice.supplier, invoice.company) != (claim.supplier, claim.company) or billed != expected:
		frappe.throw(
			_("Purchase Invoice {0} must pay Examiner Remuneration Claim {1} as approved: {2} for {3}. Cancel and amend the claim to change it.").format(
				invoice.name, claim.name, fmt_money(claim.total_amount, currency=claim.currency), claim.supplier
			)
		)


def check_tds_and_charges(invoice, claim):
	if claim.tds_section and (not invoice.apply_tds or any(not row.apply_tds for row in invoice.items)):
		frappe.throw(_("Purchase Invoice {0} must withhold TDS ({1}) as Examiner Remuneration Claim {2} does.").format(invoice.name, claim.tds_section, claim.name))
	taxes = tax_accounts(invoice.company)
	for row in invoice.taxes:
		if row.is_tax_withholding_account or row.add_deduct_tax == "Deduct" or row.account_head in taxes:
			continue
		if flt(row.base_tax_amount):
			frappe.throw(_("Row {0}: Purchase Invoice {1} of Examiner Remuneration Claim {2} cannot add a charge ({3}).").format(row.idx, invoice.name, claim.name, row.account_head))


def tax_accounts(company):
	"""The company's Tax ledgers and the GST accounts of GST Settings (GST is a tax even without a GSTIN)."""
	accounts = set(frappe.get_all("Account", {"company": company, "account_type": "Tax"}, pluck="name"))
	if frappe.db.exists("DocType", "GST Account"):
		fields = ["cgst_account", "sgst_account", "igst_account", "cess_account", "cess_non_advol_account"]
		for row in frappe.get_all("GST Account", {"parenttype": "GST Settings", "company": company}, fields, as_list=True):
			accounts |= {account for account in row if account}
	return accounts


def refuse_invoice_cancel(invoice, method=None):
	"""Purchase Invoice before_cancel: the invoice of a submitted claim is cancelled only by cancelling the claim, so
	the claim never stays submitted (holding its work) over a cancelled invoice."""
	name = paid_claim(invoice)
	if name:
		frappe.throw(_("Purchase Invoice {0} pays Examiner Remuneration Claim {1}: cancel the claim first.").format(invoice.name, name))


# ---- setup --------------------------------------------------------------------------------------------------------


def setup_remuneration():
	seed_salary_component()
	seed_policy()


def seed_salary_component():
	"""Campus's own earning component, created once and never changed afterwards."""
	if frappe.db.exists("Salary Component", SALARY_COMPONENT):
		return
	frappe.get_doc(
		{
			"doctype": "Salary Component", "salary_component": SALARY_COMPONENT, "salary_component_abbr": "CEXR", "type": "Earning",
			"description": "Examination remuneration (OneBook Campus)", "is_tax_applicable": 1, "depends_on_payment_days": 0,
		}
	).insert(ignore_permissions=True)  # fmt: skip


def seed_policy():
	"""One Accounts Manager level (limited to the claim's company), unless the institution has its own policy."""
	if frappe.db.exists("Approval Policy", {"document_type": CLAIM}):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": POLICY, "document_type": CLAIM,
			"levels": [{"approver_type": "Role", "approver": "Accounts Manager", "limit_to_company": 1, "title": "Accounts", "sla_hours": 72}],
		}
	).insert(ignore_permissions=True)  # fmt: skip
