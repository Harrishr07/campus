"""NFR Mandatory approval (BRD 16.2): sensitive document types listed in Campus Settings > Approval Required DocTypes
are never submitted when no Approval Policy matches them; the attempt is refused and names the missing configuration.

Unlisted document types keep the engine's default (no matching policy: the document submits directly). The list
is seeded once (after_install, and a patch on existing sites) with the sensitive document types that use the
approval engine; the college edits it afterwards. Certificate Request is not listed: its Certificate Type's
Needs Approval already refuses issue without an approval, and types that need none are issued directly.

A refusal is flagged for configuration: the throw rolls the transaction back, so an after_rollback callback writes an
Error Log naming the document type and user, and alerts the System Managers; once per document type per day.
"""

from functools import partial

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.utils import today
from frappe.utils.user import get_users_with_role

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
	"Credit Recognition",  # X-03: clears a degree requirement (M03-09 / M05-15)
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
		frappe.db.after_rollback.add(partial(flag_for_configuration, doc.doctype, frappe.session.user))
		frappe.throw(
			_("No approval policy is configured for {0}; ask the administrator to set one up.").format(_(doc.doctype)),
			title=_("Approval Policy Missing"),
		)


def flag_title(doctype):
	return f"Approval policy missing for {doctype}"


def flag_for_configuration(doctype, user):
	"""After the refused transaction rolled back: an Error Log and a System Manager alert, unless flagged today.

	Best effort: it runs inside frappe.db.rollback(), so any failure here is swallowed and must never replace
	the refusal the user sees or stop the other rollback callbacks."""
	try:
		write_flag(doctype, user)
	except Exception:
		pass  # the alert is optional; the refusal already stands


def write_flag(doctype, user):
	title = flag_title(doctype)
	if frappe.db.exists("Error Log", {"method": title, "creation": [">=", today()]}):
		return
	frappe.get_doc(
		{
			"doctype": "Error Log",
			"method": title,
			"error": f"{doctype} was refused for {user}: it is on Campus Settings > Approval Required DocTypes "
			"and no enabled Approval Policy matches it.",
			"reference_doctype": "DocType",
			"reference_name": doctype,
		}
	).insert(ignore_permissions=True)
	enqueue_create_notification(
		get_users_with_role("System Manager"),
		{
			"type": "Alert",
			"subject": _("{0} needs an Approval Policy: a submission was refused.").format(_(doctype)),
			"email_content": _(
				"{0} is on Approval Required DocTypes but no Approval Policy matches it. {1} was refused today."
			).format(_(doctype), user),
			"document_type": "Campus Settings",
			"document_name": "Campus Settings",
		},
	)
	frappe.db.commit()


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
