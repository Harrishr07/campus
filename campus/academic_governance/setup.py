"""M02-01 Academic Governance setup, run on install and migrate (idempotent)."""

import frappe

from campus.academic_governance.seed import mark_confidential, seed_body_types, seed_message_templates, seed_proposal_types


def setup_academic_governance():
	seed_body_types()
	seed_proposal_types()
	mark_confidential()
	seed_message_templates()


def clear_stale_proposal_references():
	"""Meeting agenda and resolution rows kept a plain-text proposal name before Academic Proposal existed; blank the
	ones that name no Academic Proposal so the rows can be saved as Links. Re-runnable."""
	proposal = frappe.qb.DocType("Academic Proposal")
	for doctype in ("Meeting Resolution", "Meeting Agenda Item"):
		row = frappe.qb.DocType(doctype)
		(
			frappe.qb.update(row)
			.set(row.proposal, None)
			.where(row.proposal.isnotnull())
			.where(row.proposal.notin(frappe.qb.from_(proposal).select(proposal.name)))
		).run()
