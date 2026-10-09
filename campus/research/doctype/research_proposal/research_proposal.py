"""M08-02 Research Proposal: a college's proposal to a Research Call, with its PI, co-PIs and budget by the scheme's
heads. The scheme must be usable by the college (every head mapped to its accounts, campus.research.api).

Internal review runs through the approval engine (default policy: the college's Principal; the PI and co-PIs never
review their own proposal). Review can't be skipped: a proposal submits only on final approval, even when no policy
matches. Once approved, `submit_to_agency` records the date it went to the agency, and `record_outcome` the agency's
decision. Until it is submitted to the agency, the PI gets deadline reminders (campus.research.proposals).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from campus.campus_platform.api import ApprovableDocument, is_approved
from campus.research.api import validate_scheme_usable

OUTCOMES = ("Sanctioned", "Not Sanctioned")
# Set only by submit_to_agency / record_outcome (db_set); never by saving the submitted form
AGENCY_FIELDS = ("status", "submission_date", "agency_reference", "outcome", "outcome_date")


class ResearchProposal(ApprovableDocument, Document):
	def validate(self):
		super().validate()
		self.set_from_call()
		validate_scheme_usable(self.funding_scheme, self.company)
		self.check_investigators()
		self.check_budget()
		self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		self.total_budget = sum(flt(row.amount) for row in self.budget)
		if self.docstatus == 0:
			self.status = "Draft"

	def before_submit(self):
		super().before_submit()
		if not is_approved(self):
			frappe.throw(
				_("{0} needs internal review: set up an Approval Policy for Research Proposal and request approval.").format(
					self.name
				)
			)
		self.status = "Approved"

	def before_update_after_submit(self):
		before = self.get_doc_before_save()
		changed = [field for field in AGENCY_FIELDS if before and str(before.get(field) or "") != str(self.get(field) or "")]
		if changed:
			frappe.throw(_("Use Submit to Agency or Record Outcome to change {0}.").format(", ".join(changed)))

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def approval_excluded_users(self):
		"""The PI and co-PIs never review their own proposal."""
		employees = [self.principal_investigator, *(row.employee for row in self.co_investigators)]
		return frappe.get_all("Employee", {"name": ["in", employees]}, pluck="user_id")

	@frappe.whitelist()
	def submit_to_agency(self, submission_date=None, agency_reference=None):
		"""Record that the internally approved proposal went to the agency."""
		self.check_permission("submit")
		status = self.locked_status()
		if self.docstatus != 1 or not is_approved(self):
			frappe.throw(_("{0} can be submitted to the agency only after internal approval.").format(self.name))
		if status != "Approved":
			frappe.throw(_("{0} is already {1}.").format(self.name, _(status).lower()))
		submission_date = getdate(submission_date or today())
		if submission_date > getdate(today()):
			frappe.throw(_("The submission date can't be in the future."))
		self.db_set(
			{"status": "Submitted to Agency", "submission_date": submission_date, "agency_reference": agency_reference}
		)
		self.add_comment(
			"Info",
			_("Submitted to the agency on {0}, reference {1}.").format(
				frappe.format(submission_date, "Date"), agency_reference or _("none")
			),
		)

	@frappe.whitelist()
	def record_outcome(self, outcome, outcome_date=None):
		"""Record the agency's decision on a proposal submitted to it."""
		self.check_permission("submit")
		if outcome not in OUTCOMES:
			frappe.throw(_("The outcome must be one of: {0}.").format(", ".join(_(o) for o in OUTCOMES)))
		if self.locked_status() != "Submitted to Agency":
			frappe.throw(_("Record the outcome once {0} is submitted to the agency.").format(self.name))
		outcome_date = getdate(outcome_date or today())
		self.db_set({"status": outcome, "outcome": outcome, "outcome_date": outcome_date})
		self.add_comment("Info", _("Agency outcome: {0} on {1}.").format(_(outcome), frappe.format(outcome_date, "Date")))

	def locked_status(self):
		"""The stored status, read under a row lock so two clicks can't both pass the status check."""
		return frappe.db.get_value(self.doctype, self.name, "status", for_update=True)

	def set_from_call(self):
		"""Agency, scheme and deadline come from the call; posted values are ignored."""
		call = frappe.db.get_value(
			"Research Call", self.research_call, ["funding_agency", "funding_scheme", "deadline"], as_dict=True
		)
		if not call:
			frappe.throw(_("Research Call {0} does not exist.").format(self.research_call))
		self.funding_agency, self.funding_scheme, self.deadline = call.funding_agency, call.funding_scheme, call.deadline

	def check_investigators(self):
		co_pis = [row.employee for row in self.co_investigators]
		if self.principal_investigator in co_pis:
			frappe.throw(_("The principal investigator can't also be a co-investigator."))
		if len(set(co_pis)) != len(co_pis):
			frappe.throw(_("A co-investigator is listed more than once."))
		companies = dict(
			frappe.get_all(
				"Employee", {"name": ["in", [self.principal_investigator, *co_pis]]}, ["name", "company"], as_list=True
			)
		)
		outside = [e for e in [self.principal_investigator, *co_pis] if companies.get(e) != self.company]
		if outside:
			frappe.throw(_("Investigators {0} are not employees of {1}.").format(", ".join(outside), self.company))

	def check_budget(self):
		if not self.budget:
			frappe.throw(_("Enter the budget by head."))
		scheme_heads = set(
			frappe.get_all(
				"Funding Scheme Head", {"parent": self.funding_scheme, "parenttype": "Funding Scheme"}, pluck="budget_head"
			)
		)
		seen = set()
		for row in self.budget:
			if row.budget_head not in scheme_heads:
				frappe.throw(
					_("Row {0}: {1} is not a budget head of Funding Scheme {2}.").format(
						row.idx, row.budget_head, self.funding_scheme
					)
				)
			if row.budget_head in seen:
				frappe.throw(_("Row {0}: budget head {1} is listed more than once.").format(row.idx, row.budget_head))
			seen.add(row.budget_head)
			if flt(row.amount) <= 0:
				frappe.throw(_("Row {0}: enter an amount for {1}.").format(row.idx, row.budget_head))
