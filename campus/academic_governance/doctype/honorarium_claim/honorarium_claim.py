"""M02-05 Honorarium Claim: an External Member's honorarium, TA and DA for a Body Meeting they attended.

Needs an approved approval request (Accounts Manager of the company by default; the requester and owner cannot approve;
the engine's submit guard refuses a submit without it). The final approval submits the claim, which drafts a Purchase
Invoice for the member's Supplier. TDS is not computed here: ERPNext / india_compliance withhold per the Supplier's Tax
Withholding Category (rate and threshold) on the honorarium, the DA and the TA; TA is left out only when claimed at
actuals with the bill attached (ruling P2-T04 fix 1, docs/rulings.md). One live claim per member per meeting, checked
under a lock on the meeting row with locking re-reads. The creator must be able to read the meeting (confidential bodies).
When Accounts submits or cancels the invoice, the claim's TDS and net figures follow it (honorarium.refresh_claim).
Cancelling the claim deletes a draft invoice; it is refused once the invoice is submitted.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from campus.academic_governance import honorarium
from campus.campus_platform.api import ApprovableDocument

ACCOUNTS_ROLES = ("Accounts User", "Accounts Manager")


class HonorariumClaim(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.check_meeting_access()
		self.set_from_masters()
		self.total_amount = flt(self.honorarium) + flt(self.travel_allowance) + flt(self.daily_allowance)
		if flt(self.honorarium) <= 0:
			frappe.throw(_("Enter the honorarium."))
		self.check_ta_bill()
		honorarium.service_items(self)
		self.check_meeting_and_duplicates()

	def on_submit(self):
		invoice = honorarium.draft_purchase_invoice(self)
		self.db_set({"purchase_invoice": invoice.name, **honorarium.payable_figures(invoice)})

	def before_cancel(self):
		if self.purchase_invoice and frappe.db.get_value("Purchase Invoice", self.purchase_invoice, "docstatus", for_update=True) == 1:
			frappe.throw(_("Purchase Invoice {0} is submitted; cancel it in Accounts first.").format(self.purchase_invoice))

	def on_cancel(self):
		"""A draft invoice goes with the claim; a cancelled one stays (Accounts' record) and stays linked."""
		if self.purchase_invoice and frappe.db.get_value("Purchase Invoice", self.purchase_invoice, "docstatus") == 0:
			invoice, self.purchase_invoice = self.purchase_invoice, None
			self.db_set("purchase_invoice", None)
			frappe.delete_doc("Purchase Invoice", invoice, ignore_permissions=True)

	def live_figures(self):
		"""TDS and net payable for the voucher: from the linked invoice as it stands now while it is draft or submitted;
		the stored figures (zeroed when Accounts cancelled it) otherwise, with `cancelled` set."""
		status = self.purchase_invoice and frappe.db.get_value("Purchase Invoice", self.purchase_invoice, "docstatus")
		if status is not None and status < 2 and self.purchase_invoice:
			return frappe._dict(honorarium.payable_figures(frappe.get_doc("Purchase Invoice", self.purchase_invoice)), cancelled=False)
		return frappe._dict(tds_amount=self.tds_amount, net_payable=self.net_payable, cancelled=status == 2)

	def check_meeting_access(self):
		"""The creator (or whoever moves the claim to another meeting) must be able to read that meeting."""
		if self.is_new() or self.has_value_changed("body_meeting"):
			frappe.has_permission("Body Meeting", "read", doc=self.body_meeting, throw=True)

	def set_from_masters(self):
		"""Company, body and date from the meeting; Supplier and TDS section from the member's Supplier. Posted values are ignored."""
		meeting = frappe.db.get_value("Body Meeting", self.body_meeting, ["company", "body", "meeting_date"], as_dict=True)
		if not meeting:
			frappe.throw(_("Body Meeting {0} does not exist.").format(self.body_meeting))
		self.company, self.body, self.meeting_date = meeting.company, meeting.body, meeting.meeting_date
		self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		member = frappe.db.get_value("External Member", self.external_member, ["member_name", "supplier"], as_dict=True)
		if not member:
			frappe.throw(_("External Member {0} does not exist.").format(self.external_member))
		self.member_name, self.supplier = member.member_name, member.supplier
		if not self.supplier:
			frappe.throw(_("{0} has no Supplier; create one from the External Member first.").format(self.member_name))
		self.tds_section = frappe.db.get_value("Supplier", self.supplier, "tax_withholding_category")
		if not self.tds_section:
			frappe.throw(_("Ask Accounts to set the TDS category on Supplier {0}.").format(self.supplier))

	def check_ta_bill(self):
		"""TA at actuals needs the bill as a File attached to this claim, uploaded by the claim's owner or by Accounts."""
		if not self.ta_actuals:
			return
		owner = self.ta_bill and frappe.db.get_value(
			"File", {"file_url": self.ta_bill, "attached_to_doctype": self.doctype, "attached_to_name": self.name}, "owner"
		)
		if not owner:
			frappe.throw(_("Attach the travel bill to this claim (save it first), then tick TA at Actuals."))
		if owner != self.owner and not set(ACCOUNTS_ROLES) & set(frappe.get_roles(owner)):
			frappe.throw(_("The travel bill must be uploaded by {0} or by Accounts.").format(self.owner))

	def ta_exempt(self):
		"""TA is left out of TDS only at actuals with the bill attached."""
		return bool(self.ta_actuals and self.ta_bill)

	def check_meeting_and_duplicates(self):
		"""Lock the meeting, then re-read attendance and other claims with locking reads."""
		status, meeting_date = frappe.db.get_value("Body Meeting", self.body_meeting, ["status", "meeting_date"], for_update=True)
		if status == "Cancelled" or getdate(meeting_date) > getdate(today()):
			frappe.throw(_("Honorarium is claimed only for a meeting that has taken place."))
		if not honorarium.attended(self.body_meeting, self.external_member):
			frappe.throw(_("{0} did not attend {1}.").format(self.member_name, self.body_meeting))
		other = honorarium.other_claim(self.body_meeting, self.external_member, self.name)
		if other:
			frappe.throw(_("{0} already has Honorarium Claim {1} for {2}.").format(self.member_name, other, self.body_meeting))
