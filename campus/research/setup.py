"""M08-02 Research setup, run on install and migrate (idempotent): the PI deadline reminder template and the default
internal review policy for Research Proposals (P3-T13), and the "Institution" Funding Agency that seed money is
sanctioned under (P3-T14), the `oc_budget_head` custom fields on purchase, journal and expense claim lines (P3-T15)
the Utilisation Certificate approval policy, PI -> Accounts -> Principal (P3-T17), and the PFMS vendor fields on
Supplier with the placeholder PFMS EAT export layouts (P3-T18).
Existing (possibly edited) records are left alone."""

import frappe

from campus.research.budget_control import setup_budget_head_fields
from campus.research.pfms import seed_layouts, setup_pfms_fields
from campus.research.utilisation import UC_DOCTYPE, UC_POLICY

REMINDER_EVENT = "research_proposal.deadline"
REVIEW_POLICY = "Research Proposal Internal Review"
INSTITUTION_AGENCY = "Institution"


def setup_research():
	seed_research()
	setup_budget_head_fields()
	setup_pfms_fields()


def seed_research():
	"""The records only (no custom field DDL), so tests can call it."""
	seed_reminder_template()
	seed_review_policy()
	seed_institution_agency()
	seed_uc_policy()
	seed_layouts()


def seed_reminder_template():
	if frappe.db.exists("Message Template", REMINDER_EVENT):
		return
	frappe.get_doc(
		{
			"doctype": "Message Template",
			"event_key": REMINDER_EVENT,
			"purpose": "transactional",
			"channels": [{"channel": "email"}, {"channel": "whatsapp"}, {"channel": "sms"}],
			"bodies": [
				{
					"language": "en",
					"subject": "Proposal due: {{ doc.title }}",
					"body": "Your proposal \"{{ doc.title }}\" ({{ doc.name }}) for {{ doc.funding_agency }} is due on "
					"{{ frappe.format(context.deadline, {'fieldtype': 'Date'}) }}. It is {{ doc.status }} and not yet "
					"submitted to the agency.",
				}
			],
		}
	).insert(ignore_permissions=True)


def seed_review_policy():
	"""One level: the Principal of the proposal's college."""
	if frappe.db.exists("Approval Policy", {"document_type": "Research Proposal"}):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": REVIEW_POLICY, "document_type": "Research Proposal",
			"levels": [{"approver_type": "Role", "approver": "Principal", "limit_to_company": 1, "title": "Internal Review", "sla_hours": 72}],
		}
	).insert(ignore_permissions=True)  # fmt: skip


def seed_institution_agency():
	"""The college's own seed money is a grant like any other, from this agency."""
	if frappe.db.exists("Funding Agency", INSTITUTION_AGENCY):
		return
	frappe.get_doc(
		{"doctype": "Funding Agency", "agency_name": INSTITUTION_AGENCY, "agency_type": "Institution"}
	).insert(ignore_permissions=True)


def seed_uc_policy():
	"""The PI certifies, then Accounts, then the Principal of the certificate's college."""
	if frappe.db.exists("Approval Policy", {"document_type": UC_DOCTYPE}):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": UC_POLICY, "document_type": UC_DOCTYPE,
			"levels": [
				{"title": "Principal Investigator", "approver_type": "Field", "approver": "pi_user", "sla_hours": 72},
				{"title": "Accounts", "approver_type": "Role", "approver": "Accounts Manager", "limit_to_company": 1, "sla_hours": 72},
				{"title": "Principal", "approver_type": "Role", "approver": "Principal", "limit_to_company": 1, "sla_hours": 72},
			],
		}
	).insert(ignore_permissions=True)  # fmt: skip
