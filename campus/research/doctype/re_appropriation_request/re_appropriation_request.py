"""M08-04 Re-appropriation Request: the agency's approval, by letter, to move an amount from one head of a submitted
Sanction to another for a fiscal year. Submitting it moves the amount between the sanction's head rows, revises the
Budgets (campus.research.budget_sync) and logs the change on the sanction; cancelling moves it back. The total sanctioned
doesn't change. A head can't give away money already spent or committed against it, checked under the sanction lock
(campus.research.budget_control)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from campus.research.budget_control import head_overspend
from campus.research.budget_sync import sync_budgets


class ReappropriationRequest(Document):
	def validate(self):
		sanction = frappe.db.get_value("Sanction", self.sanction, ["docstatus", "company", "funding_scheme", "currency"], as_dict=True)
		if not sanction or sanction.docstatus != 1:
			frappe.throw(_("Sanction {0} must be submitted to re-appropriate its heads.").format(self.sanction))
		self.company, self.currency = sanction.company, sanction.currency
		if self.from_head == self.to_head:
			frappe.throw(_("The from and to heads are the same."))
		if flt(self.amount) <= 0:
			frappe.throw(_("Enter the amount to re-appropriate."))
		scheme_heads = frappe.get_all(
			"Funding Scheme Head", {"parent": sanction.funding_scheme, "parenttype": "Funding Scheme"}, pluck="budget_head"
		)
		if self.to_head not in scheme_heads:
			frappe.throw(_("{0} is not a budget head of Funding Scheme {1}.").format(self.to_head, sanction.funding_scheme))
		self.check_available(self.from_head)

	def before_submit(self):
		self.move(self.from_head, self.to_head)
		self.log(_("Re-appropriation {0}: {1} moved from {2} to {3} for {4} under agency letter {5} of {6}."))

	def on_cancel(self):
		self.move(self.to_head, self.from_head)
		self.log(_("Re-appropriation {0} cancelled: {1} moved back from {3} to {2} for {4} (agency letter {5} of {6})."))

	def move(self, source, target):
		# one change to the heads at a time; the locking read sees a sanction cancelled meanwhile
		if frappe.db.get_value("Sanction", self.sanction, "docstatus", for_update=True) != 1:
			frappe.throw(_("Sanction {0} must be submitted to re-appropriate its heads.").format(self.sanction))
		self.check_available(source, for_update=True)
		self.add_to_head(source, -flt(self.amount))
		self.add_to_head(target, flt(self.amount))
		sanction = frappe.get_doc("Sanction", self.sanction)
		sanction.check_revenue_head_accounts()  # a revenue head newly on the sanction needs its own single account
		breach = head_overspend(self.sanction, source)
		if breach:
			frappe.throw(
				_("{0} has already spent or committed {1} up to the end of {2}; after this only {3} would be sanctioned.").format(
					source, frappe.format(breach.spent, "Currency"), breach.period, frappe.format(breach.limit, "Currency")
				)
			)
		sync_budgets(self.sanction)

	def head_row(self, head, for_update=False):
		return frappe.db.get_value(
			"Sanction Head",
			{"parent": self.sanction, "parenttype": "Sanction", "budget_head": head, "fiscal_year": self.fiscal_year},
			["name", "amount"], as_dict=True, for_update=for_update,
		)  # fmt: skip

	def check_available(self, head, for_update=False):
		row = self.head_row(head, for_update)
		available = flt(row.amount) if row else 0
		if flt(self.amount, 2) > flt(available, 2):
			frappe.throw(
				_("{0} has {1} sanctioned for {2}; {3} can't be moved from it.").format(
					head, frappe.format(available, "Currency"), self.fiscal_year, frappe.format(self.amount, "Currency")
				)
			)

	def add_to_head(self, head, amount):
		"""Change the head's row for the year; a row left at zero is removed, a missing one added."""
		row = self.head_row(head, for_update=True)
		if row:
			remaining = flt(row.amount) + amount
			if flt(remaining, 2) <= 0:
				frappe.db.delete("Sanction Head", row.name)
			else:
				frappe.db.set_value("Sanction Head", row.name, "amount", remaining)
			return
		last = frappe.db.get_value("Sanction Head", {"parent": self.sanction, "parenttype": "Sanction"}, "max(idx)") or 0
		frappe.get_doc(
			{
				"doctype": "Sanction Head", "parent": self.sanction, "parenttype": "Sanction", "parentfield": "heads",
				"idx": last + 1, "budget_head": head, "fiscal_year": self.fiscal_year, "amount": amount,
				"is_capital": frappe.db.get_value("Grant Budget Head", head, "is_capital"),
			}  # fmt: skip
		).db_insert()

	def log(self, message):
		frappe.get_doc("Sanction", self.sanction).add_comment(
			"Info",
			message.format(
				self.name, frappe.format(self.amount, "Currency"), self.from_head, self.to_head, self.fiscal_year,
				self.agency_letter_no, frappe.format(self.agency_letter_date, "Date"),
			),
		)  # fmt: skip
