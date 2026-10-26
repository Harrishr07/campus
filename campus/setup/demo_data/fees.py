"""PR-03 Fees of the 2026 intake: the admission invoices paid in full, in part or not at all.

The invoices themselves were raised by Confirm Joining; payments are ordinary Payment Entries made from them
(`get_payment_entry`), so the receivable, the student's fee ledger and the dues check all read real vouchers."""

import frappe
from frappe.utils import flt, getdate

from campus.setup.demo_data import intake

PAID_IN_FULL, PAID_IN_PART = (
	(1, 2, 3, 4),
	(5,),
)  # applicant ordinals (see intake.ORDINALS); joiners 6 and 7 stay outstanding


def load(ctx):
	"""Pay the open admission invoices of the college by the applicant's ordinal in the programme, so adding joiners later changes
	nobody's payment: ordinals 1-4 in full, 5 half, the rest not at all."""
	ordinals = {a.person.email: a.ordinal for a in intake.plan(ctx)}
	invoices = frappe.get_all(
		"Sales Invoice",
		{"company": ctx.college, "docstatus": 1, "is_return": 0, "oc_program_enrollment": ["is", "set"]},
		["name", "student", "grand_total", "outstanding_amount"], order_by="creation, name", limit=0,
	)  # fmt: skip
	for invoice in invoices:
		ordinal = ordinals.get(frappe.db.get_value("Student", invoice.student, "student_email_id"))
		if ordinal in PAID_IN_FULL:
			pay(ctx, invoice, invoice.grand_total)
		elif ordinal in PAID_IN_PART:
			pay(ctx, invoice, round(invoice.grand_total / 2))


def pay(ctx, invoice, amount):
	"""A submitted Payment Entry of `amount` against the invoice, unless it has been paid (the outstanding is below the amount)."""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	if flt(invoice.outstanding_amount) < flt(amount) or frappe.db.exists(
		"Payment Entry Reference", {"reference_name": invoice.name, "docstatus": 1}
	):
		return
	payment = get_payment_entry("Sales Invoice", invoice.name, party_amount=amount)
	payment.reference_no, payment.reference_date = f"DEMO-UTR-{invoice.student}", getdate()
	payment.insert(ignore_permissions=True).submit()
	ctx.out.created["Payment Entry"] += 1
