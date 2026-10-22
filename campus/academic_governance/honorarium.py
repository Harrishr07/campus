"""M02-05 Honorarium for external members: the draft Purchase Invoice a claim makes, the claim's figures following
that invoice (Purchase Invoice doc events), the attendance and duplicate checks (locking reads), and the seeded approval policy. The service Items of the invoice lines are chosen by Accounts in
Governance Settings (they carry the SAC code and expense account), so none is seeded."""

import frappe
from frappe import _
from frappe.utils import flt, today

HONORARIUM_POLICY = "Honorarium Claim Approval"


def draft_purchase_invoice(claim):
	"""A draft Purchase Invoice for the claim's Supplier. ERPNext / india_compliance withhold TDS on the lines marked for it
	(honorarium, DA, and TA unless at actuals with a bill) per the Supplier's Tax Withholding Category; Accounts reviews
	and submits it. Runs as the approver, who may lack Purchase Invoice rights: every input comes from the server-validated claim."""
	items = service_items(claim)
	invoice = frappe.new_doc("Purchase Invoice")
	invoice.update(
		{
			"company": claim.company, "supplier": claim.supplier, "posting_date": today(), "bill_no": claim.name, "apply_tds": 1,
			"remarks": _("Honorarium Claim {0}: {1}, {2}").format(claim.name, claim.member_name, claim.body_meeting),
		}
	)  # fmt: skip
	invoice.append("items", line(items.honorarium_item, _("Honorarium"), claim.honorarium, claim.tds_section))
	if flt(claim.daily_allowance):
		invoice.append("items", line(items.daily_allowance_item, _("Daily Allowance"), claim.daily_allowance, claim.tds_section))
	if flt(claim.travel_allowance):
		invoice.append("items", line(items.travel_item, _("Travel Allowance"), claim.travel_allowance, None if claim.ta_exempt() else claim.tds_section))
	invoice.flags.ignore_permissions = True
	invoice.insert()
	return invoice


def service_items(claim):
	"""The Items of the lines the claim needs, from Governance Settings (one per line: ERPNext refuses a repeated Item);
	throws naming a missing one, or an Item without the HSN/SAC code india_compliance requires on the invoice."""
	settings = frappe.get_single("Governance Settings")
	needed = {"honorarium_item": True, "travel_item": flt(claim.travel_allowance), "daily_allowance_item": flt(claim.daily_allowance)}
	items = frappe._dict()
	for fieldname, is_needed in needed.items():
		if not is_needed:
			continue
		label, items[fieldname] = _(settings.meta.get_label(fieldname)), settings.get(fieldname)
		if not items[fieldname]:
			frappe.throw(_("Set the {0} in Governance Settings.").format(label))
		if frappe.get_meta("Item").has_field("gst_hsn_code") and not frappe.db.get_value("Item", items[fieldname], "gst_hsn_code"):
			frappe.throw(_("Item {0} ({1} in Governance Settings) has no HSN/SAC code.").format(items[fieldname], label))
	return items


def line(item_code, description, amount, tds_section):
	return {
		"item_code": item_code, "description": description, "qty": 1, "rate": amount,
		"apply_tds": 1 if tds_section else 0, "tax_withholding_category": tds_section,
	}  # fmt: skip


def withheld(invoice):
	"""TDS on the invoice (its tax withholding rows)."""
	return sum(row.base_tax_amount for row in invoice.taxes if row.is_tax_withholding_account)


def payable_figures(invoice):
	return {"tds_amount": withheld(invoice), "net_payable": invoice.rounded_total or invoice.grand_total}


def refresh_claim(invoice, method=None):
	"""Purchase Invoice on_submit / on_cancel: the claim it pays follows its figures. A submitted amendment of the
	claim's cancelled invoice becomes the claim's invoice; a cancelled invoice leaves nothing payable."""
	links = [invoice.name, invoice.amended_from] if invoice.amended_from else [invoice.name]
	claim = frappe.db.get_value("Honorarium Claim", {"purchase_invoice": ["in", links], "docstatus": 1}, "name", for_update=True)
	if not claim:
		return
	if invoice.docstatus == 2:
		# runs after ERPNext's on_cancel set its own list, before the back-link check
		invoice.ignore_linked_doctypes = (*(invoice.get("ignore_linked_doctypes") or ()), "Honorarium Claim")
		values = {"tds_amount": 0, "net_payable": 0}
	else:
		values = {"purchase_invoice": invoice.name, **payable_figures(invoice)}
	frappe.db.set_value("Honorarium Claim", claim, values)


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

