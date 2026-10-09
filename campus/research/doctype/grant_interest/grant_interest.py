"""M08-05 Grant Interest: interest the bank credits on a sanction's grant funds (blueprint D9). On submit it posts a
Journal Entry debiting the bank / cash account and crediting, per the agency's or college's interest treatment
(campus.research.api.interest_treatment), the sanction's "Grant Received in Advance" liability (the default: the
interest is refundable or adds to the grant) or the college's Interest Income Account. The sanction's set-up is re-read
under a lock on it. A closed sanction (Project Closure) takes no interest, and its interest can't be cancelled."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from campus.research.api import check_sanction_open, interest_treatment

SANCTION_FIELDS = ["docstatus", "company", "funding_agency", "liability_account", "cost_center", "project", "project_closure"]


class GrantInterest(Document):
	def validate(self):
		sanction = self.get_sanction()
		self.company, self.funding_agency = sanction.company, sanction.funding_agency
		if flt(self.amount) <= 0:
			frappe.throw(_("Enter the interest amount."))
		self.check_received_in()
		self.set_credited_to(sanction)

	def before_submit(self):
		sanction = self.get_sanction(for_update=True)  # a concurrent cancel removed the set-up: refused
		self.set_credited_to(sanction)
		self.journal_entry = self.make_journal_entry(sanction)

	def before_cancel(self):
		check_sanction_open(self.sanction, self.get_sanction(for_update=True).project_closure)

	def on_cancel(self):
		if self.journal_entry and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
			entry = frappe.get_doc("Journal Entry", self.journal_entry)
			entry.flags.ignore_permissions = True
			entry.cancel()

	def get_sanction(self, for_update=False):
		sanction = frappe.db.get_value("Sanction", self.sanction, SANCTION_FIELDS, as_dict=True, for_update=for_update)
		if not sanction or sanction.docstatus != 1:
			frappe.throw(_("Sanction {0} must be submitted to record interest on it.").format(self.sanction))
		if self.docstatus != 2:
			check_sanction_open(self.sanction, sanction.project_closure)
		return sanction

	def set_credited_to(self, sanction):
		self.interest_treatment = interest_treatment(sanction.company, sanction.funding_agency)
		if self.interest_treatment == "Interest Income":
			self.credited_to = frappe.db.get_value("Research Settings", sanction.company, "interest_income_account")
		else:
			self.credited_to = sanction.liability_account

	def check_received_in(self):
		account = frappe.db.get_value("Account", self.received_in, ["company", "is_group", "account_type"], as_dict=True)
		if not account or account.company != self.company or account.is_group or account.account_type not in ("Bank", "Cash"):
			frappe.throw(_("Credited In must be a bank or cash ledger of {0}.").format(self.company))

	def make_journal_entry(self, sanction):
		voucher_type = "Bank Entry" if frappe.db.get_value("Account", self.received_in, "account_type") == "Bank" else "Cash Entry"
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry", "voucher_type": voucher_type, "company": self.company,
				"posting_date": self.posting_date, "cheque_no": self.reference_no,
				"cheque_date": self.posting_date if self.reference_no else None,
				"user_remark": _("Grant Interest {0} on Sanction {1}").format(self.name, self.sanction),
				"accounts": [
					{"account": self.received_in, "debit_in_account_currency": self.amount, "cost_center": sanction.cost_center},
					{
						"account": self.credited_to, "credit_in_account_currency": self.amount,
						"cost_center": sanction.cost_center, "project": sanction.project,
					},
				],
			}  # fmt: skip
		)
		entry.flags.ignore_permissions = True
		entry.insert()
		entry.submit()
		return entry.name
