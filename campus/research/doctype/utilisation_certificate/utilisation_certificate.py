"""M08-06 Utilisation Certificate and Statement of Expenditure of a sanction for a period (blueprint D9).

The figures (opening unspent, grants received, interest, total available, expenditure by budget head, closing unspent)
are read from the GL on every save of a draft not in approval (campus.research.utilisation). Approval runs PI ->
Accounts -> Principal through the approval engine (the seeded "Utilisation Certificate Approval" policy); a UC submits
only on final approval. Under a lock on the sanction, the final approval re-reads the ledger with locking reads and is
refused while the project has unreconciled spending, while the figures differ from those approved, or while another
submitted UC of the sanction covers part of the period. Approval stores a snapshot of the figures, the certifiers and
issues the printed certificate as a Verifiable Document in the scheme's or agency's UC Format (placeholder GFR 12-A
style print by default). A later GL entry dated up to the period end that moves the figures marks it "source
changed"; a revision is a cancel and amend, numbered as the next version."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from campus.campus_platform import verification
from campus.campus_platform.api import ApprovableDocument, is_approved, latest_request
from campus.research.api import check_sanction_open
from campus.research.grant_recognition import lock_sanction
from campus.research.utilisation import (
	FIGURE_FIELDS,
	HEAD_FIELDS,
	mark_source,
	signature,
	snapshot,
	utilisation_figures,
)

DEFAULT_FORMAT = "Utilisation Certificate"
LEVEL_FIELDS = {1: "pi_certified_by", 2: "accounts_certified_by", 3: "principal_certified_by"}


class UtilisationCertificate(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		sanction = self.set_from_sanction()
		self.check_period(sanction)
		if self.is_new():
			self.set_version()
		self.print_format = certificate_format(sanction.funding_scheme, sanction.funding_agency)
		if self.figures_open():
			self.set_figures(utilisation_figures(self.sanction, self.from_date, self.to_date))

	def before_submit(self):
		super().before_submit()
		if not is_approved(self):
			frappe.throw(_("{0} needs approval by the PI, Accounts and the Principal. Use Request Approval.").format(self.name))
		sanction = lock_sanction(self.sanction)
		if sanction.docstatus != 1:
			frappe.throw(_("Sanction {0} must be submitted.").format(self.sanction))
		self.check_overlap()
		figures = utilisation_figures(self.sanction, self.from_date, self.to_date, lock=True)
		if figures.unreconciled:
			vouchers = ", ".join(f"{row.voucher_type} {row.voucher_no}" for row in figures.unreconciled[:5])
			frappe.throw(
				_("{0} can't be approved: spending on the project without a budget head of Sanction {1} is unreconciled ({2}). Post it to a head or move it off the project first.").format(
					self.name, self.sanction, vouchers
				)
			)
		if signature(figures) != signature(self):
			frappe.throw(
				_("The ledger of Sanction {0} changed after {1} was sent for approval. Return it for changes and save it again.").format(
					self.sanction, self.name
				)
			)
		self.snapshot, self.source_changed, self.source_changed_on = snapshot(figures), 0, None
		self.set_certifiers()
		self.check_distinct_certifiers()

	def on_submit(self):
		self.db_set("verification_code", verification.issue(self, self.print_format).code)

	def on_cancel(self):
		verification.revoke_for(self, _("Utilisation Certificate {0} was cancelled.").format(self.name))

	@frappe.whitelist()
	def recheck_source(self):
		"""Recompute an approved UC from the ledger and set (or clear) Source Changed; returns the flag."""
		self.check_permission("submit")
		if self.docstatus != 1:
			frappe.throw(_("Only an approved certificate is checked against its source."))
		return mark_source(self)

	def set_from_sanction(self):
		sanction = frappe.db.get_value(
			"Sanction", self.sanction,
			["docstatus", "title", "company", "funding_agency", "funding_scheme", "sanction_order_no", "principal_investigator",
			 "pi_name", "project", "cost_center", "liability_account", "start_date", "end_date", "project_closure"],
			as_dict=True,
		)  # fmt: skip
		if not sanction or sanction.docstatus != 1:
			frappe.throw(_("Sanction {0} must be submitted.").format(self.sanction))
		if self.docstatus == 0:  # a closed sanction gets no new certificates
			check_sanction_open(self.sanction, sanction.project_closure)
		for field in ("title", "company", "funding_agency", "funding_scheme", "sanction_order_no", "principal_investigator",
			"pi_name", "project", "cost_center", "liability_account"):  # fmt: skip
			self.set(field, sanction[field])
		self.pi_user = frappe.db.get_value("Employee", sanction.principal_investigator, "user_id")
		self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		return sanction

	def check_period(self, sanction):
		if getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(_("The From Date can't be after the To Date."))
		if getdate(self.from_date) < getdate(sanction.start_date) or getdate(self.to_date) > getdate(sanction.end_date):
			frappe.throw(
				_("The period must be inside the sanction period ({0} to {1}).").format(
					frappe.format(sanction.start_date, "Date"), frappe.format(sanction.end_date, "Date")
				)
			)

	def set_version(self):
		if self.amended_from:
			self.version = (frappe.db.get_value(self.doctype, self.amended_from, "version") or 0) + 1
			return
		earlier = frappe.get_all(
			self.doctype, {"sanction": self.sanction, "from_date": self.from_date, "to_date": self.to_date}, pluck="version"
		)
		self.version = max(earlier or [0]) + 1

	def figures_open(self):
		"""A draft's figures follow the ledger until it is sent for approval."""
		if self.docstatus != 0:
			return False
		latest = None if self.is_new() else latest_request(self)
		return not latest or latest.status not in ("Pending", "Approved")

	def set_figures(self, figures):
		for field in FIGURE_FIELDS:
			self.set(field, figures[field])
		self.unreconciled_entries = len(figures.unreconciled)
		self.set("heads", [{field: row[field] for field in HEAD_FIELDS} | {"currency": self.currency} for row in figures.heads])

	def check_overlap(self):
		uc = frappe.qb.DocType(self.doctype)
		other = (
			frappe.qb.from_(uc).select(uc.name)
			.where(
				(uc.sanction == self.sanction) & (uc.docstatus == 1) & (uc.name != self.name)
				& (uc.from_date <= self.to_date) & (uc.to_date >= self.from_date)
			)
			.for_update().run(pluck=True)
		)  # fmt: skip
		if other:
			frappe.throw(_("Utilisation Certificate {0} of Sanction {1} already covers part of this period.").format(other[0], self.sanction))

	def approval_excluded_users(self):
		"""Who already approved an earlier level of the pending approval: one person certifies at one level only."""
		latest = None if self.is_new() else latest_request(self)
		if not latest or latest.status != "Pending":
			return []
		request = frappe.get_doc("Approval Request", latest.name)
		return [
			action.approver for action in request.actions
			if action.cycle == request.cycle and action.action == "Approve" and action.level < request.current_level
		]  # fmt: skip

	def check_distinct_certifiers(self):
		certifiers = [self.get(field) for field in LEVEL_FIELDS.values() if self.get(field)]
		twice = sorted({user for user in certifiers if certifiers.count(user) > 1})
		if twice:
			frappe.throw(_("{0} can't certify {1} at more than one level.").format(", ".join(twice), self.name))

	def set_certifiers(self):
		"""Who approved each level in the approval that is submitting the UC."""
		request = frappe.get_doc("Approval Request", latest_request(self).name)
		for action in request.actions:
			if action.cycle == request.cycle and action.action == "Approve" and action.level in LEVEL_FIELDS:
				self.set(LEVEL_FIELDS[action.level], action.approver)


def certificate_format(scheme, agency):
	"""The Utilisation Certificate print format named by the scheme's UC Format, else the agency's, else the default."""
	name = (
		frappe.db.get_value("Funding Scheme", scheme, "uc_format")
		or frappe.db.get_value("Funding Agency", agency, "uc_format")
		or DEFAULT_FORMAT
	)
	if not frappe.db.exists("Print Format", {"name": name, "doc_type": "Utilisation Certificate"}):
		frappe.throw(_("UC Format {0} is not a print format of Utilisation Certificate.").format(frappe.bold(name)))
	return name
