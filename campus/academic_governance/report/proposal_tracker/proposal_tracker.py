"""M02-02 Proposal Tracker: every Academic Proposal of a company with its status, the body it awaits and the
resolution that approved it. Read through get_list, so User Permissions apply."""

import frappe
from frappe import _
from frappe.utils import date_diff, today

FIELDS = ["name", "title", "proposal_type", "department", "regulation", "curriculum", "status", "current_stage",
	"current_body_type", "approved_on", "approving_resolution", "creation"]  # fmt: skip


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		return columns(), []
	query = {key: filters[key] for key in ("company", "status", "proposal_type", "department") if filters.get(key)}
	rows = frappe.get_list("Academic Proposal", query, FIELDS, order_by="creation desc")
	return columns(), [row_of(row) for row in rows]


def row_of(proposal):
	return {
		"proposal": proposal.name, "title": proposal.title, "proposal_type": proposal.proposal_type,
		"department": proposal.department, "regulation": proposal.regulation, "curriculum": proposal.curriculum,
		"status": proposal.status, "stage": stage_label(proposal),
		"days_open": date_diff(proposal.approved_on or today(), proposal.creation),
		"approved_on": proposal.approved_on, "approving_resolution": proposal.approving_resolution,
	}  # fmt: skip


def stage_label(proposal):
	if proposal.status == "In Route":
		route = frappe.get_cached_doc("Proposal Type", proposal.proposal_type).route
		return f"{proposal.current_stage}/{len(route)} {proposal.current_body_type}"
	return _(proposal.status)


def columns():
	def col(fieldname, label, fieldtype="Data", width=120, options=None):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "width": width, "options": options}

	return [
		col("proposal", "Proposal", "Link", 140, "Academic Proposal"),
		col("title", "Title", width=220),
		col("proposal_type", "Type", "Link", 140, "Proposal Type"),
		col("department", "Department", "Link", 170, "Department"),
		col("regulation", "Regulation", "Link", 120, "Regulation"),
		col("curriculum", "Curriculum", "Link", 150, "Curriculum"),
		col("status", "Status", width=90),
		col("stage", "Stage", width=190),
		col("days_open", "Days Open", "Int", 90),
		col("approved_on", "Approved On", "Date", 110),
		col("approving_resolution", "Approving Resolution", width=200),
	]
