"""M08-02 Research Proposal Pipeline: a college's proposals with their stage, from draft through internal review and
agency submission to the agency's outcome. Read through get_list, so User Permissions apply."""

import frappe
from frappe import _

from campus.campus_platform.api import latest_request

FIELDS = ["name", "title", "status", "principal_investigator", "pi_name", "research_call", "funding_agency",
	"funding_scheme", "deadline", "total_budget", "currency", "submission_date", "outcome_date"]  # fmt: skip
DRAFT_STAGES = {"Pending": "Under Internal Review", "Returned": "Returned for Changes", "Rejected": "Rejected Internally"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		return columns(), []
	query = {key: filters[key] for key in ("company", "funding_agency", "research_call", "status") if filters.get(key)}
	rows = frappe.get_list("Research Proposal", query, FIELDS, order_by="deadline asc, creation desc")
	return columns(), [row_of(row) for row in rows]


def stage(status, approval_status):
	"""A draft's stage is where its internal review stands; after that the stage is the proposal's status."""
	if status == "Draft":
		return DRAFT_STAGES.get(approval_status, "Draft")
	return status


def row_of(proposal):
	request = latest_request(frappe._dict(doctype="Research Proposal", name=proposal.name))
	return {
		"proposal": proposal.name, "title": proposal.title,
		"stage": _(stage(proposal.status, request and request.status)),
		"principal_investigator": proposal.principal_investigator, "pi_name": proposal.pi_name,
		"research_call": proposal.research_call, "funding_agency": proposal.funding_agency,
		"funding_scheme": proposal.funding_scheme, "deadline": proposal.deadline,
		"total_budget": proposal.total_budget, "currency": proposal.currency,
		"submission_date": proposal.submission_date, "outcome_date": proposal.outcome_date,
	}  # fmt: skip


def columns():
	def col(fieldname, label, fieldtype="Data", width=120, options=None):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "width": width, "options": options}

	return [
		col("proposal", "Proposal", "Link", 150, "Research Proposal"),
		col("title", "Title", width=220),
		col("stage", "Stage", width=160),
		col("principal_investigator", "PI", "Link", 120, "Employee"),
		col("pi_name", "PI Name", width=160),
		col("research_call", "Research Call", "Link", 150, "Research Call"),
		col("funding_agency", "Funding Agency", "Link", 160, "Funding Agency"),
		col("funding_scheme", "Funding Scheme", "Link", 160, "Funding Scheme"),
		col("deadline", "Deadline", "Date", 100),
		col("total_budget", "Total Budget", "Currency", 130, "currency"),
		col("currency", "Currency", "Link", 80, "Currency"),
		col("submission_date", "Submitted On", "Date", 110),
		col("outcome_date", "Outcome Date", "Date", 110),
	]
