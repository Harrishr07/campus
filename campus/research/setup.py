"""M08-02 Research setup, run on install and migrate (idempotent): the PI deadline reminder template and the default
internal review policy for Research Proposals (P3-T13), and the "Institution" Funding Agency that seed money is
sanctioned under (P3-T14), the `oc_budget_head` custom fields on purchase, journal and expense claim lines (P3-T15)
the Utilisation Certificate approval policy, PI -> Accounts -> Principal (P3-T17), and the PFMS vendor fields on
Supplier with the placeholder PFMS EAT export layouts (P3-T18), and for project staff (P3-T19) the "Project Staff"
Employment Type, the JRF / SRF / Project Assistant designations and the "Fellowship" salary component, with the
progress report fields on Project Update, the IPR committee policy for Invention Disclosures (P3-T21), and for
consultancy (P3-T20) the `oc_consultancy_project` field on Sales Invoice, the "Consultancy Share" salary component and
the revenue share approval policy (Accounts, then the Principal).
Existing (possibly edited) records are left alone."""

import frappe

from campus.research.budget_control import setup_budget_head_fields
from campus.research.consultancy import seed_salary_component, setup_consultancy_fields
from campus.research.pfms import seed_layouts, setup_pfms_fields
from campus.research.progress import setup_progress_fields
from campus.research.utilisation import UC_DOCTYPE, UC_POLICY

REMINDER_EVENT = "research_proposal.deadline"
REVIEW_POLICY = "Research Proposal Internal Review"
DISCLOSURE_POLICY = "Invention Disclosure Committee"
SHARE_POLICY = "Consultancy Revenue Share Approval"
INSTITUTION_AGENCY = "Institution"
PROJECT_STAFF = "Project Staff"
PROJECT_STAFF_DESIGNATIONS = ("Junior Research Fellow", "Senior Research Fellow", "Project Assistant")
FELLOWSHIP_COMPONENT = "Fellowship"


def setup_research():
	seed_research()
	setup_budget_head_fields()
	setup_pfms_fields()
	setup_progress_fields()
	setup_consultancy_fields()


def seed_research():
	"""The records only (no custom field DDL), so tests can call it."""
	seed_reminder_template()
	seed_review_policy()
	seed_disclosure_policy()
	seed_institution_agency()
	seed_uc_policy()
	seed_layouts()
	seed_project_staff()
	seed_salary_component()
	seed_share_policy()


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


def seed_disclosure_policy():
	"""One level: the Principal of the disclosure's college acts as the IPR committee (P3-T21)."""
	if frappe.db.exists("Approval Policy", {"document_type": "Invention Disclosure"}):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": DISCLOSURE_POLICY, "document_type": "Invention Disclosure",
			"levels": [{"approver_type": "Role", "approver": "Principal", "limit_to_company": 1, "title": "IPR Committee", "sla_hours": 168}],
		}
	).insert(ignore_permissions=True)  # fmt: skip


def seed_share_policy():
	"""Accounts checks the receipt and split, then the Principal of the share's college approves the payout (P3-T20)."""
	if frappe.db.exists("Approval Policy", {"document_type": "Consultancy Revenue Share"}):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": SHARE_POLICY, "document_type": "Consultancy Revenue Share",
			"levels": [
				{"title": "Accounts", "approver_type": "Role", "approver": "Accounts Manager", "limit_to_company": 1, "sla_hours": 72},
				{"title": "Principal", "approver_type": "Role", "approver": "Principal", "limit_to_company": 1, "sla_hours": 72},
			],
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


def seed_project_staff():
	"""Project staff are Employees of this Employment Type, paid a fellowship through payroll. The college maps the
	Fellowship component to its Manpower head's account and builds the fellowship Salary Structure."""
	if not frappe.db.exists("Employment Type", PROJECT_STAFF):
		frappe.get_doc({"doctype": "Employment Type", "employee_type_name": PROJECT_STAFF}).insert(ignore_permissions=True)
	for designation in PROJECT_STAFF_DESIGNATIONS:
		if not frappe.db.exists("Designation", designation):
			frappe.get_doc({"doctype": "Designation", "designation_name": designation}).insert(ignore_permissions=True)
	if not frappe.db.exists("Salary Component", FELLOWSHIP_COMPONENT):
		frappe.get_doc(
			{
				"doctype": "Salary Component", "salary_component": FELLOWSHIP_COMPONENT, "salary_component_abbr": "FEL",
				"type": "Earning", "depends_on_payment_days": 1,
				"description": "Fellowship of project staff (JRF / SRF / Project Assistant), paid from the sanction's Manpower head.",
			}  # fmt: skip
		).insert(ignore_permissions=True)
