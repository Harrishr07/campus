"""M08-02 Research setup, run on install and migrate (idempotent): the PI deadline reminder template and the default
internal review policy for Research Proposals. Existing (possibly edited) records are left alone."""

import frappe

REMINDER_EVENT = "research_proposal.deadline"
REVIEW_POLICY = "Research Proposal Internal Review"


def setup_research():
	seed_reminder_template()
	seed_review_policy()


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
