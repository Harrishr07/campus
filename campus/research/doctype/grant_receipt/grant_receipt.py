"""M08-03 Grant Receipt: money received against an instalment of a submitted Sanction. On submit it posts a Journal
Entry debiting the bank / cash account and crediting the sanction's "Grant Received in Advance" liability with its
project and cost centre (blueprint D9: a receipt is never income; income is recognised later as the grant is spent).
A Journal Entry is used rather than a Payment Entry because a Funding Agency is not an ERPNext party.

An instalment can't be received beyond its amount; the check runs under a lock on the sanction."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Sum
from frappe.utils import flt

SANCTION_FIELDS = ["docstatus", "company", "funding_agency", "currency", "liability_account", "cost_center", "project"]


class GrantReceipt(Document):
	def validate(self):
		sanction = self.get_sanction()
		if sanction.docstatus != 1:
			frappe.throw(_("Sanction {0} must be submitted to receive money against it.").format(self.sanction))
		self.company, self.funding_agency, self.currency = sanction.company, sanction.funding_agency, sanction.currency
		if flt(self.amount) <= 0:
			frappe.throw(_("Enter the amount received."))
		if self.instalment_amount() is None:
			frappe.throw(_("{0} is not an instalment of Sanction {1}.").format(self.instalment, self.sanction))
		self.check_received_in()

	def before_submit(self):
		frappe.db.get_value("Sanction", self.sanction, "name", for_update=True)  # one receipt at a time per sanction
		balance = flt(self.instalment_amount()) - self.received_so_far()
		if flt(self.amount, 2) > flt(balance, 2):
			frappe.throw(
				_("Instalment {0} of {1} has a balance of {2}; {3} can't be received.").format(
					self.instalment, self.sanction, frappe.format(balance, "Currency"), frappe.format(self.amount, "Currency")
				)
			)
		self.journal_entry = self.make_journal_entry()

	def on_submit(self):
		update_received(self.sanction)

	def on_cancel(self):
		if self.journal_entry:
			entry = frappe.get_doc("Journal Entry", self.journal_entry)
			if entry.docstatus == 1:
				entry.flags.ignore_permissions = True
				entry.cancel()
		update_received(self.sanction)

	def get_sanction(self):
		sanction = frappe.db.get_value("Sanction", self.sanction, SANCTION_FIELDS, as_dict=True)
		if not sanction:
			frappe.throw(_("Sanction {0} does not exist.").format(self.sanction))
		return sanction

	def instalment_amount(self):
		return frappe.db.get_value(
			"Sanction Instalment", {"parent": self.sanction, "parenttype": "Sanction", "instalment": self.instalment}, "amount"
		)

	def received_so_far(self):
		"""Other submitted receipts of this instalment, read with a locking read (the sanction lock is already held)."""
		rows = frappe.db.sql(
			"""select coalesce(sum(amount), 0) from `tabGrant Receipt`
			where sanction = %s and instalment = %s and docstatus = 1 and name != %s for update""",
			(self.sanction, self.instalment, self.name),
		)
		return flt(rows[0][0])

	def check_received_in(self):
		account = frappe.db.get_value("Account", self.received_in, ["company", "is_group", "account_type"], as_dict=True)
		if not account or account.company != self.company or account.is_group or account.account_type not in ("Bank", "Cash"):
			frappe.throw(_("Received In must be a bank or cash ledger of {0}.").format(self.company))
		self.voucher_type = "Bank Entry" if account.account_type == "Bank" else "Cash Entry"

	def make_journal_entry(self):
		sanction = self.get_sanction()
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry", "voucher_type": self.voucher_type, "company": self.company,
				"posting_date": self.posting_date, "cheque_no": self.reference_no, "cheque_date": self.reference_date,
				"user_remark": _("Grant Receipt {0}: instalment {1} of Sanction {2}").format(self.name, self.instalment, self.sanction),
				"accounts": [
					{"account": self.received_in, "debit_in_account_currency": self.amount, "cost_center": sanction.cost_center},
					{
						"account": sanction.liability_account, "credit_in_account_currency": self.amount,
						"cost_center": sanction.cost_center, "project": sanction.project,
					},
				],
			}  # fmt: skip
		)
		entry.flags.ignore_permissions = True
		entry.insert()
		entry.submit()
		return entry.name


def update_received(sanction):
	"""Write each instalment's received amount and the sanction's total from its submitted receipts."""
	receipt = frappe.qb.DocType("Grant Receipt")
	received = dict(
		frappe.qb.from_(receipt)
		.select(receipt.instalment, Sum(receipt.amount))
		.where((receipt.sanction == sanction) & (receipt.docstatus == 1))
		.groupby(receipt.instalment)
		.run()
	)
	for row in frappe.get_all("Sanction Instalment", {"parent": sanction, "parenttype": "Sanction"}, ["name", "instalment"]):
		frappe.db.set_value("Sanction Instalment", row.name, "received_amount", flt(received.get(row.instalment)))
	frappe.db.set_value("Sanction", sanction, "total_received", sum(flt(v) for v in received.values()))
