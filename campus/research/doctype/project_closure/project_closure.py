"""M08-09 Project Closure of a sanctioned project (blueprint D9).

The closure names the final Utilisation Certificate: an approved (submitted) UC of the sanction, its latest. On submit,
under a lock on the sanction, it is refused while any ledger entry on the sanction's liability or cost centre is dated
after the final UC's period end, or while the UC's figures no longer match the ledger (locking re-reads). The unspent
balance is the final UC's closing unspent. It leaves the "Grant Received in Advance" liability by a Journal Entry
dated after the final UC's period:
- Refund to Agency: to the bank or cash ledger the refund is paid from (a Funding Agency is not an ERPNext party);
- Retain per Agency Letter: to the ledger the agency letter names (its number, date and attachment are required).
Nothing is posted when nothing is unspent. The Project is then Completed and the sanction closed: no further spending
(campus.research.budget_control), receipts or project staff appointments. Cancelling reverses all of it.
Asset handover to the department is deferred (docs/usage/research.md)."""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from campus.research.api import check_sanction_open
from campus.research.utilisation import UC_DOCTYPE, signature, utilisation_figures

REFUND, RETAIN = "Refund to Agency", "Retain per Agency Letter"
SANCTION_FIELDS = [
	"name", "docstatus", "title", "company", "funding_agency", "currency", "project", "cost_center", "liability_account",
	"project_closure",
]  # fmt: skip
UC_FIELDS = ["name", "sanction", "docstatus", "from_date", "to_date", "closing_unspent", "source_changed", "snapshot"]


class ProjectClosure(Document):
	def validate(self):
		sanction = self.get_sanction()
		for field in ("title", "company", "funding_agency", "currency", "project", "cost_center", "liability_account"):
			self.set(field, sanction[field])
		if not self.final_uc:
			return  # mandatory
		uc = self.get_final_uc()
		if getdate(self.posting_date) <= getdate(uc.to_date):
			frappe.throw(
				_("The closure must be dated after the final UC's period end {0}.").format(frappe.format(uc.to_date, "Date"))
			)
		self.unspent_balance = flt(uc.closing_unspent, 2)
		self.check_treatment()

	def before_submit(self):
		sanction = self.get_sanction(for_update=True)  # spending and receipts on the sanction wait for the closure
		uc = self.get_final_uc(for_update=True)
		self.check_latest(uc)
		self.check_nothing_after(sanction, uc.to_date)
		figures = utilisation_figures(self.sanction, uc.from_date, uc.to_date, lock=True)
		stored = json.loads(uc.snapshot or "{}")
		if signature(figures) != {"figures": stored.get("figures"), "heads": stored.get("heads")}:
			frappe.throw(
				_("The ledger of Sanction {0} changed after the final UC {1} was approved: revise the UC (cancel and amend) first.").format(
					self.sanction, uc.name
				)
			)
		self.unspent_balance = flt(figures.closing_unspent, 2)
		self.check_treatment()
		if self.unspent_balance > 0:
			self.journal_entry = self.make_journal_entry(sanction)

	def on_submit(self):
		frappe.db.set_value("Project", self.project, "status", "Completed")
		frappe.db.set_value("Sanction", self.sanction, "project_closure", self.name)

	def on_cancel(self):
		frappe.db.get_value("Sanction", self.sanction, "name", for_update=True)
		if self.journal_entry and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
			entry = frappe.get_doc("Journal Entry", self.journal_entry)
			entry.flags.ignore_permissions = True
			entry.cancel()
		frappe.db.set_value("Project", self.project, "status", "Open")
		frappe.db.set_value("Sanction", self.sanction, "project_closure", None)

	def get_sanction(self, for_update=False):
		sanction = frappe.db.get_value("Sanction", self.sanction, SANCTION_FIELDS, as_dict=True, for_update=for_update)
		if not sanction or sanction.docstatus != 1:
			frappe.throw(_("Sanction {0} must be submitted.").format(self.sanction))
		if sanction.project_closure != self.name:
			check_sanction_open(sanction.name, sanction.project_closure)
		return sanction

	def get_final_uc(self, for_update=False):
		uc = frappe.db.get_value(UC_DOCTYPE, self.final_uc, UC_FIELDS, as_dict=True, for_update=for_update)
		if not uc or uc.sanction != self.sanction:
			frappe.throw(_("{0} is not a Utilisation Certificate of Sanction {1}.").format(self.final_uc, self.sanction))
		if uc.docstatus != 1:
			frappe.throw(_("The final Utilisation Certificate {0} must be approved first.").format(uc.name))
		if uc.source_changed:
			frappe.throw(_("The final Utilisation Certificate {0} is marked Source Changed: revise it first.").format(uc.name))
		return uc

	def check_latest(self, uc):
		table = frappe.qb.DocType(UC_DOCTYPE)
		later = (
			frappe.qb.from_(table).select(table.name)
			.where((table.sanction == self.sanction) & (table.docstatus == 1) & (table.to_date > uc.to_date))
			.for_update().run(pluck=True)
		)  # fmt: skip
		if later:
			frappe.throw(_("{0} is not the latest Utilisation Certificate of Sanction {1}: {2} runs later.").format(uc.name, self.sanction, later[0]))

	def check_nothing_after(self, sanction, to_date):
		"""Locking reads on the indexed liability account and cost centre: a voucher committed while we waited is seen."""
		for field, value in (("account", sanction.liability_account), ("cost_center", sanction.cost_center)):
			entry = frappe.db.get_value(
				"GL Entry", {field: value, "is_cancelled": 0, "posting_date": [">", to_date]}, ["voucher_type", "voucher_no"],
				as_dict=True, for_update=True,
			)  # fmt: skip
			if entry:
				frappe.throw(
					_("Sanction {0} has ledger entries after the final UC's period end {1} ({2} {3}): certify them in a final UC first.").format(
						self.sanction, frappe.format(to_date, "Date"), _(entry.voucher_type), entry.voucher_no
					)
				)

	def check_treatment(self):
		if self.treatment == REFUND:
			if self.unspent_balance > 0:
				self.check_paid_from()
			return
		if not (self.agency_letter_no and self.agency_letter_date and self.agency_letter):
			frappe.throw(_("Enter the agency letter number, date and attachment that let the college retain the unspent balance."))
		if self.unspent_balance > 0:
			self.check_retained_to()

	def check_paid_from(self):
		account = frappe.db.get_value("Account", self.paid_from, ["company", "is_group", "account_type"], as_dict=True) if self.paid_from else None
		if not account or account.company != self.company or account.is_group or account.account_type not in ("Bank", "Cash"):
			frappe.throw(_("Paid From must be a bank or cash ledger of {0}.").format(self.company))
		if account.account_type == "Bank" and not (self.reference_no and self.reference_date):
			frappe.throw(_("Enter the UTR / cheque number and date of the refund."))

	def check_retained_to(self):
		account = frappe.db.get_value("Account", self.retained_to, ["company", "is_group", "root_type"], as_dict=True) if self.retained_to else None
		if (
			not account or account.company != self.company or account.is_group
			or account.root_type not in ("Liability", "Income", "Equity") or self.retained_to == self.liability_account
		):  # fmt: skip
			frappe.throw(_("Retained To must be a liability, income or equity ledger of {0}, other than the grant liability.").format(self.company))

	def make_journal_entry(self, sanction):
		refund = self.treatment == REFUND
		to_account = self.paid_from if refund else self.retained_to
		voucher_type = "Journal Entry"
		if refund:
			voucher_type = "Bank Entry" if frappe.db.get_value("Account", to_account, "account_type") == "Bank" else "Cash Entry"
		remark = _("Project Closure {0} of Sanction {1}: unspent balance {2}").format(
			self.name, self.sanction, _("refunded to the agency") if refund else _("retained per agency letter {0}").format(self.agency_letter_no)
		)
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry", "voucher_type": voucher_type, "company": self.company, "posting_date": self.posting_date,
				"cheque_no": self.reference_no if refund else self.agency_letter_no,
				"cheque_date": self.reference_date if refund else self.agency_letter_date, "user_remark": remark,
				"accounts": [
					{"account": sanction.liability_account, "debit_in_account_currency": self.unspent_balance,
					 "cost_center": sanction.cost_center, "project": sanction.project},
					{"account": to_account, "credit_in_account_currency": self.unspent_balance, "cost_center": sanction.cost_center},
				],
			}  # fmt: skip
		)
		entry.flags.ignore_permissions = True
		entry.insert()
		entry.submit()
		return entry.name
