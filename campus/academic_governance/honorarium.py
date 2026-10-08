"""M02-05 Honorarium for external members: the draft Purchase Invoice a claim makes, the attendance and duplicate
checks (locking reads), and the seeded approval policy. The service Items of the invoice lines are chosen by Accounts in
Governance Settings (they carry the SAC code and expense account), so none is seeded."""

import frappe
from frappe import _
from frappe.utils import today

HONORARIUM_POLICY = "Honorarium Claim Approval"


def draft_purchase_invoice(claim):
	"""A draft Purchase Invoice for the claim's Supplier. ERPNext / india_compliance withhold TDS on the honorarium line
	per the claim's Tax Withholding Category; Accounts reviews and submits it. Runs as the approver, who may lack
	Purchase Invoice rights: every input comes from the server-validated claim."""
	honorarium_item, travel_item = service_items(claim)
	invoice = frappe.new_doc("Purchase Invoice")
	invoice.update(
		{
			"company": claim.company, "supplier": claim.supplier, "posting_date": today(), "bill_no": claim.name,
			"apply_tds": 1 if claim.tds_section else 0,
			"remarks": _("Honorarium Claim {0}: {1}, {2}").format(claim.name, claim.member_name, claim.body_meeting),
		}
	)  # fmt: skip
	invoice.append("items", line(honorarium_item, claim.honorarium, claim.tds_section))
	if claim.ta_da:
		invoice.append("items", line(travel_item, claim.ta_da, None))
	invoice.flags.ignore_permissions = True
	invoice.insert()
	return invoice


def service_items(claim):
	"""(honorarium Item, travel Item) from Governance Settings; throws when one the claim needs is not set."""
	items = frappe.db.get_single_value("Governance Settings", "honorarium_item"), frappe.db.get_single_value("Governance Settings", "travel_item")
	if not items[0] or (claim.ta_da and not items[1]):
		frappe.throw(_("Set the Honorarium Item and Travel Item in Governance Settings."))
	return items


def line(item_code, amount, tds_section):
	return {
		"item_code": item_code, "qty": 1, "rate": amount,
		"apply_tds": 1 if tds_section else 0, "tax_withholding_category": tds_section,
	}  # fmt: skip


def withheld(invoice):
	"""TDS on the invoice (its tax withholding rows)."""
	return sum(row.base_tax_amount for row in invoice.taxes if row.is_tax_withholding_account)


def attended(meeting, member):
	"""True if `member` is marked present in the stored attendance of `meeting` (locking read)."""
	return bool(
		frappe.db.get_value(
			"Meeting Attendance",
			{"parenttype": "Body Meeting", "parent": meeting, "external_member": member, "present": 1},
			"name",
			for_update=True,
		)
	)


def other_claim(meeting, member, exclude):
	"""Another live (draft or submitted) claim of `member` for `meeting` (locking read)."""
	claim = frappe.qb.DocType("Honorarium Claim")
	rows = (
		frappe.qb.from_(claim)
		.select(claim.name)
		.where((claim.body_meeting == meeting) & (claim.external_member == member) & (claim.docstatus < 2))
		.where(claim.name != (exclude or ""))
		.limit(1)
		.for_update()
	).run()
	return rows[0][0] if rows else None


def seed_honorarium_policy():
	"""One Accounts Manager level (limited to the claim's company), unless the institution has its own policy."""
	if frappe.db.exists("Approval Policy", {"document_type": "Honorarium Claim"}):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": HONORARIUM_POLICY, "document_type": "Honorarium Claim",
			"levels": [{"approver_type": "Role", "approver": "Accounts Manager", "limit_to_company": 1, "title": "Accounts", "sla_hours": 72}],
		}
	).insert(ignore_permissions=True)  # fmt: skip

