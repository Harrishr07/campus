"""M08-05 Grant Income Recognition: the period-end grant accounting entry of blueprint D9 for a college's sanctions.

On submit one Journal Entry, posted on the period end, recognises per sanction (campus.research.grant_recognition):
revenue spent (liability -> grant income), assets bought (liability -> Deferred Capital Grant) and the release of the
Deferred Capital Grant in line with depreciation (-> grant income). With no sanctions listed, every submitted sanction
of the college started by the period end is taken. A sanction already recognised to the period end (or a later one), or
with nothing to recognise, is dropped; when none is left the run is refused, so running a period twice posts nothing.

Each sanction is locked while its amounts are re-read with locking reads, and its row carries the unique key
(sanction, period end). Cancelling reverses the entry and frees the key; only a sanction's latest recognition can be
cancelled."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from campus.research.api import get_research_settings
from campus.research.grant_recognition import journal_rows, lock_sanction, recognised, recognition_amounts, spent_to

AMOUNT_FIELDS = {"revenue": "revenue_amount", "capital": "capital_amount", "release": "release_amount"}


class GrantIncomeRecognition(Document):
	def validate(self):
		if getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(_("The From Date can't be after the To Date."))
		self.posting_date = self.to_date
		if not self.sanctions:
			self.add_sanctions()
		self.check_sanctions()
		for row in self.sanctions:  # a preview; recomputed under the lock on submit
			self.set_amounts(row, frappe.db.get_value("Sanction", row.sanction, ["name", "company", "cost_center"], as_dict=True))

	def before_submit(self):
		kept = []
		for row in sorted(self.sanctions, key=lambda r: r.sanction):  # one lock order across runs
			sanction = lock_sanction(row.sanction)
			if sanction.docstatus != 1:
				frappe.throw(_("Sanction {0} must be submitted to recognise its grant income.").format(row.sanction))
			if self.set_amounts(row, sanction, lock=True):
				row.recognition_key = f"{row.sanction}|{getdate(self.to_date)}"
				kept.append((row, sanction))
		if not kept:
			frappe.throw(
				_("Nothing to recognise up to {0}: the sanctions are already recognised for the period or have nothing new.").format(
					frappe.format(self.to_date, "Date")
				)
			)
		self.set("sanctions", [row for row, _sanction in kept])
		self.journal_entry = self.make_journal_entry(kept)

	def on_cancel(self):
		for row in sorted(self.sanctions, key=lambda r: r.sanction):
			lock_sanction(row.sanction)
			self.check_latest(row.sanction)
		if self.journal_entry and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
			entry = frappe.get_doc("Journal Entry", self.journal_entry)
			entry.flags.ignore_permissions = True
			entry.cancel()
		for row in self.sanctions:
			row.db_set("recognition_key", None)

	def add_sanctions(self):
		for name in frappe.get_all(
			"Sanction", {"company": self.company, "docstatus": 1, "start_date": ["<=", self.to_date]}, pluck="name", order_by="name"
		):
			self.append("sanctions", {"sanction": name})

	def check_sanctions(self):
		seen = set()
		for row in self.sanctions:
			docstatus, company = frappe.db.get_value("Sanction", row.sanction, ["docstatus", "company"]) or (None, None)
			if docstatus != 1:
				frappe.throw(_("Row {0}: Sanction {1} must be submitted.").format(row.idx, row.sanction))
			if company != self.company:
				frappe.throw(_("Row {0}: Sanction {1} is not of {2}.").format(row.idx, row.sanction, self.company))
			if row.sanction in seen:
				frappe.throw(_("Row {0}: Sanction {1} is listed more than once.").format(row.idx, row.sanction))
			seen.add(row.sanction)

	def set_amounts(self, row, sanction, lock=False):
		"""Set the row's amounts; True when there is something to post."""
		done = recognised(row.sanction, lock=lock)
		if done.last_to_date and getdate(done.last_to_date) >= getdate(self.to_date):
			amounts = dict.fromkeys(AMOUNT_FIELDS, 0)
		else:
			amounts = recognition_amounts(spent_to(sanction, self.to_date, lock=lock), done)
		for key, field in AMOUNT_FIELDS.items():
			row.set(field, amounts[key])
		return any(amounts.values())

	def check_latest(self, sanction):
		row, doc = frappe.qb.DocType("Grant Income Recognition Sanction"), frappe.qb.DocType("Grant Income Recognition")
		later = (
			frappe.qb.from_(row).join(doc).on(doc.name == row.parent)
			.select(doc.name)
			.where(
				(row.sanction == sanction) & (row.parenttype == self.doctype) & (doc.docstatus == 1)
				& (doc.name != self.name) & (doc.to_date > self.to_date)
			)
			.for_update().run()
		)  # fmt: skip
		if later:
			frappe.throw(
				_("Sanction {0} has a later recognition {1}: cancel it first.").format(sanction, later[0][0])
			)

	def make_journal_entry(self, kept):
		settings = get_research_settings(self.company)
		accounts = frappe._dict(income=settings.grant_income_account, deferred=settings.deferred_capital_grant_account)
		rows = []
		for row, sanction in kept:
			amounts = {key: row.get(field) for key, field in AMOUNT_FIELDS.items()}
			rows.extend(journal_rows(sanction, amounts, accounts))
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry", "voucher_type": "Journal Entry", "company": self.company,
				"posting_date": self.to_date, "accounts": rows,
				"user_remark": _("Grant Income Recognition {0} for {1} to {2}").format(
					self.name, frappe.format(self.from_date, "Date"), frappe.format(self.to_date, "Date")
				),
			}  # fmt: skip
		)
		entry.flags.ignore_permissions = True
		entry.insert()
		entry.submit()
		return entry.name
