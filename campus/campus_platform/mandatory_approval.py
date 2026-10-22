"""NFR Mandatory approval (BRD 16.2): sensitive document types listed in Campus Settings > Approval Required DocTypes
are never submitted when no Approval Policy matches them; the attempt is refused and names the missing configuration.

Unlisted document types keep the engine's default (no matching policy: the document submits directly). The list
is seeded once (after_install, and a patch on existing sites) with the sensitive document types that use the
approval engine; the college edits it afterwards. Certificate Request is not listed: its Certificate Type's
Needs Approval already refuses issue without an approval, and types that need none are issued directly.
"""

import frappe
from frappe import _

SETTINGS_FIELD = "approval_required_doctypes"
ROW_DOCTYPE = "Approval Required Doctype"

MANDATORY_APPROVAL_DOCTYPES = (
	"Result Ratification",  # publication of revised Student Results
	"Fee Refund",
	"Fee Concession",
	"Scholarship Application",  # sanction; disbursements are rows of the sanctioned application
	"Rejoin Application",
	"Examiner Remuneration Claim",
	"Utilisation Certificate",
)


def approval_required(doctype):
	return bool(
		frappe.db.exists(
			ROW_DOCTYPE, {"parenttype": "Campus Settings", "parentfield": SETTINGS_FIELD, "document_type": doctype}
		)
	)


def refuse_without_policy(doc):
	"""Called when no Approval Policy matches `doc`: throws if its document type is on the mandatory list."""
	if approval_required(doc.doctype):
		frappe.throw(
			_("No approval policy is configured for {0}; ask the administrator to set one up.").format(_(doc.doctype)),
			title=_("Approval Policy Missing"),
		)


def uses_approval_engine(doctype):
	from frappe.model.base_document import get_controller

	from campus.campus_platform.approvals import ApprovableDocument

	try:
		return issubclass(get_controller(doctype), ApprovableDocument)
	except (ImportError, frappe.DoesNotExistError):
		return False


def missing_doctypes(listed):
	"""The seed document types that exist, use the approval engine and are not in `listed`, in seed order."""
	return [
		d
		for d in MANDATORY_APPROVAL_DOCTYPES
		if d not in listed and frappe.db.exists("DocType", d) and uses_approval_engine(d)
	]


def seed_mandatory_approval():
	settings = frappe.get_doc("Campus Settings")
	missing = missing_doctypes({row.document_type for row in settings.get(SETTINGS_FIELD)})
	for doctype in missing:
		settings.append(SETTINGS_FIELD, {"document_type": doctype})
	if missing:
		settings.flags.ignore_permissions = True
		settings.save()
