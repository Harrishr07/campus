"""M02-02 / M02-04 What final approval of an Academic Proposal does: the Regulation (for a regulation change) and
the Curriculum become Effective, the Curriculum for the listed batches only, both carrying the approving resolution.
The caller holds a savepoint, so a failure leaves neither changed."""

import frappe
from frappe import _

OPEN_STATUSES = ("Draft", "Approved")


def apply(proposal, proposal_type, resolution_no):
	if proposal_type.changes_regulation:
		make_regulation_effective(proposal.regulation, resolution_no)
	if proposal.curriculum:
		make_curriculum_effective(proposal, resolution_no)


def make_regulation_effective(name, resolution_no):
	regulation = frappe.get_doc("Regulation", name)
	if regulation.status not in OPEN_STATUSES:
		frappe.throw(
			_("Regulation {0} is {1}; only a Draft or Approved regulation can be made Effective.").format(
				frappe.bold(name), _(regulation.status)
			)
		)
	regulation.status = "Effective"
	regulation.approving_resolution = resolution_no
	regulation.flags.ignore_permissions = True  # authorised by the resolution, resolved on the server
	regulation.save()


def make_curriculum_effective(proposal, resolution_no):
	curriculum = frappe.get_doc("Curriculum", proposal.curriculum)
	if curriculum.status not in OPEN_STATUSES:
		frappe.throw(
			_("Curriculum {0} is {1}; only a Draft or Approved curriculum can be made Effective.").format(
				frappe.bold(curriculum.name), _(curriculum.status)
			)
		)
	curriculum.flags.ignore_permissions = True
	curriculum.flags.via_academic_proposal = True
	curriculum.set("applicable_batches", [{"academic_year": row.academic_year} for row in proposal.batches])
	curriculum.approving_resolution = resolution_no
	if curriculum.status == "Draft":
		curriculum.status = "Approved"
		curriculum.save()
	curriculum.status = "Effective"
	curriculum.save()
