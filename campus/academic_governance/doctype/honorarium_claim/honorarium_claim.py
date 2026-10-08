"""M02-05 Honorarium Claim: an External Member's honorarium and TA/DA for a Body Meeting they attended.

Needs an approved approval request (Accounts Manager of the company by default; the requester and owner cannot approve).
The final approval submits the claim, which drafts a Purchase Invoice for the member's Supplier. TDS is not computed
here: the honorarium line carries the claim's Tax Withholding Category and ERPNext / india_compliance withhold per its
rate and threshold; the TA/DA line is left out of withholding. One live claim per member per meeting, checked under a
lock on the meeting row with locking re-reads. Cancelling deletes the draft invoice; it is refused once that is submitted.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from campus.academic_governance import honorarium
from campus.campus_platform.api import ApprovableDocument, is_approved


class HonorariumClaim(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.set_from_masters()
		self.total_amount = flt(self.honorarium) + flt(self.ta_da)
		if flt(self.honorarium) <= 0:
			frappe.throw(_("Enter the honorarium."))
		honorarium.service_items(self)
		self.check_meeting_and_duplicates()

	def before_submit(self):
		super().before_submit()
		if not is_approved(self):
			frappe.throw(_("{0} needs approval before it can be submitted. Use Request Approval.").format(self.name))

	def on_submit(self):
		invoice = honorarium.draft_purchase_invoice(self)
		self.db_set(
			{"purchase_invoice": invoice.name, "tds_amount": honorarium.withheld(invoice), "net_payable": invoice.grand_total}
		)

	def before_cancel(self):
		if self.purchase_invoice and frappe.db.get_value("Purchase Invoice", self.purchase_invoice, "docstatus", for_update=True) == 1:
			frappe.throw(_("Purchase Invoice {0} is submitted; cancel it in Accounts first.").format(self.purchase_invoice))

	def on_cancel(self):
		invoice, self.purchase_invoice = self.purchase_invoice, None
		self.db_set("purchase_invoice", None)
		if invoice and frappe.db.exists("Purchase Invoice", invoice):
			frappe.delete_doc("Purchase Invoice", invoice, ignore_permissions=True)

	def set_from_masters(self):
		"""Company, body and date from the meeting, Supplier from the member; posted values are ignored."""
		meeting = frappe.db.get_value("Body Meeting", self.body_meeting, ["company", "body", "meeting_date"], as_dict=True)
		if not meeting:
			frappe.throw(_("Body Meeting {0} does not exist.").format(self.body_meeting))
		self.company, self.body, self.meeting_date = meeting.company, meeting.body, meeting.meeting_date
		member = frappe.db.get_value("External Member", self.external_member, ["member_name", "supplier"], as_dict=True)
		if not member:
			frappe.throw(_("External Member {0} does not exist.").format(self.external_member))
		self.member_name, self.supplier = member.member_name, member.supplier
		if not self.supplier:
			frappe.throw(_("{0} has no Supplier; create one from the External Member first.").format(self.member_name))
		if not self.tds_section:
			self.tds_section = frappe.db.get_value("Supplier", self.supplier, "tax_withholding_category")

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
