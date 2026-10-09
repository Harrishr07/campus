"""M06-04 Examiner remuneration payment: an HRMS Additional Salary on the Campus-owned component "Campus Exam
Remuneration" for internal examiners (on the next payroll), or a draft Purchase Invoice for an external examiner's
Supplier, with TDS withheld by ERPNext / india_compliance per the Supplier's Tax Withholding Category. The claim's TDS
and net figures follow the invoice when Accounts submits or cancels it (Purchase Invoice doc events). Also the seeded
component and approval policy. HRMS's own salary components are never changed."""

import frappe
from frappe import _

from campus.examinations import remuneration_rules as rules

CLAIM = "Examiner Remuneration Claim"
SALARY_COMPONENT = "Campus Exam Remuneration"
POLICY = "Examiner Remuneration Claim Approval"


# ---- internal examiners: Additional Salary ----------------------------------------------------------------------


def post_additional_salary(claim):
	"""A submitted Additional Salary for the claim total on the employee's next payroll. Runs as the approver: every
	input comes from the server-computed claim."""
	payroll_date = rules.next_payroll_date(claim.posting_date, last_processed_slip_end(claim.employee))
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


def last_processed_slip_end(employee):
	return frappe.db.get_value("Salary Slip", {"employee": employee, "docstatus": 1}, "end_date", order_by="end_date desc")


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
			"company": claim.company, "supplier": claim.supplier, "posting_date": claim.posting_date, "bill_no": claim.name, "apply_tds": 1,
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


def refuse_cancel_after_invoice(claim):
	if claim.purchase_invoice and frappe.db.get_value("Purchase Invoice", claim.purchase_invoice, "docstatus", for_update=True) == 1:
		frappe.throw(_("Purchase Invoice {0} is submitted; cancel it in Accounts first.").format(claim.purchase_invoice))


def delete_draft_invoice(claim):
	"""A draft invoice goes with the claim; a cancelled one stays (Accounts' record) and stays linked."""
	if claim.purchase_invoice and frappe.db.get_value("Purchase Invoice", claim.purchase_invoice, "docstatus") == 0:
		invoice = claim.purchase_invoice
		claim.db_set("purchase_invoice", None)
		frappe.delete_doc("Purchase Invoice", invoice, ignore_permissions=True)


def refresh_claim(invoice, method=None):
	"""Purchase Invoice on_submit / on_cancel: the claim it pays follows its figures. A submitted amendment of the
	claim's cancelled invoice becomes the claim's invoice; a cancelled invoice leaves nothing payable."""
	links = [invoice.name, invoice.amended_from] if invoice.amended_from else [invoice.name]
	claim = frappe.db.get_value(CLAIM, {"purchase_invoice": ["in", links], "docstatus": 1}, "name", for_update=True)
	if not claim:
		return
	if invoice.docstatus == 2:
		invoice.ignore_linked_doctypes = (*(invoice.get("ignore_linked_doctypes") or ()), CLAIM)
		values = {"tds_amount": 0, "net_payable": 0}
	else:
		values = {"purchase_invoice": invoice.name, **payable_figures(invoice)}
	frappe.db.set_value(CLAIM, claim, values)


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
