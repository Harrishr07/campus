"""M04-03 Document verification: the per-applicant checklist built from Admission Document Rules.

- The checklist (`oc_documents`) is rebuilt on every Student Applicant validate from the rules that apply to
  the applicant's admission type, quota and category (a blank rule field applies to all). It is idempotent:
  a document type already on the list is never duplicated, only its rule flags are refreshed, and a rule row
  that no longer applies is dropped when still Pending. Rows added by hand are left alone.
- A mandatory document is complete when it is Verified (or Submitted when the rule needs no verification).
- Only an Admission Verifier may mark a row Verified or Rejected, or move a Verified row to another status; the verifier and time are stamped.
- An applicant cannot be set Admitted while a mandatory document is incomplete.
- The daily job reminds applicants with incomplete mandatory documents, once a day, until cleared.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, nowdate

from campus.admissions.setup import VERIFIER_ROLE
from campus.campus_messaging.api import send
from campus.campus_platform.bulk import run_bulk

REMINDER_EVENT = "admission.document_pending"
REMINDER_KEY = "campus.admissions.documents.reminder_key"
REMINDER_HANDLER = "campus.admissions.documents.send_reminder"
REMINDER_RUN_TYPE = "Admission Document Reminders"
VERIFIER_STATUSES = ("Verified", "Rejected")
OPEN_STATUSES = ("Applied", "Approved")  # applicants still in the pipeline


def applicable_rules(applicant):
	"""Admission Document Rules that apply to the applicant."""
	rules = frappe.get_all(
		"Admission Document Rule",
		fields=["document_type", "mandatory", "original_retained", "verification_needed", "admission_type", "quota", "student_category"],
		order_by="creation, name",
		limit=0,
	)
	wanted = {
		"admission_type": applicant.get("oc_admission_type"),
		"quota": applicant.get("oc_admission_quota"),
		"student_category": applicant.get("student_category"),
	}
	return [r for r in rules if all(not r[k] or r[k] == v for k, v in wanted.items())]


def build_checklist(applicant):
	"""Add the applicable rules' documents to `applicant.oc_documents`; refresh flags; drop stale Pending rule rows."""
	rules = {}
	for rule in applicable_rules(applicant):
		current = rules.get(rule.document_type)
		rules[rule.document_type] = _stricter(current, rule) if current else rule
	rows = {row.document_type: row for row in applicant.oc_documents}
	for document_type, rule in rules.items():
		row = rows.get(document_type) or applicant.append("oc_documents", {"document_type": document_type, "status": "Pending"})
		row.mandatory = cint(rule.mandatory)
		row.verification_needed = cint(rule.verification_needed)
		row.original_required = cint(rule.original_retained)
		row.from_rule = cint(row.from_rule or not rows.get(document_type))
	stale = [r for r in applicant.oc_documents if r.from_rule and r.document_type not in rules and r.status == "Pending"]
	for row in stale:
		applicant.remove(row)


def _stricter(first, second):
	"""Two rules for one document type: mandatory/verification/original needs of either apply."""
	return frappe._dict(
		first,
		mandatory=cint(first.mandatory or second.mandatory),
		verification_needed=cint(first.verification_needed or second.verification_needed),
		original_retained=cint(first.original_retained or second.original_retained),
	)


def incomplete_mandatory(applicant):
	"""Document types of the applicant's mandatory documents that are not yet complete."""
	return [row.document_type for row in applicant.oc_documents if row.mandatory and not row_complete(row)]


def row_complete(row):
	if row.status == "Verified":
		return True
	return row.status == "Submitted" and not row.verification_needed


def documents_complete(applicant):
	"""True when every mandatory document of the applicant (name or document) is complete."""
	doc = frappe.get_doc("Student Applicant", applicant) if isinstance(applicant, str) else applicant
	return not incomplete_mandatory(doc)


def validate_applicant(doc, method=None):
	"""Student Applicant validate hook: checklist, verifier stamping and the admit guard."""
	build_checklist(doc)
	before = doc.get_doc_before_save()
	previous = {r.name: r.status for r in before.oc_documents} if before else {}
	for row in doc.oc_documents:
		stamp_verifier(row, previous.get(row.name))
	if doc.application_status == "Admitted" and (not before or before.application_status != "Admitted"):
		missing = incomplete_mandatory(doc)
		if missing:
			frappe.throw(_("Cannot admit: mandatory documents are not complete: {0}").format(", ".join(missing)))


def stamp_verifier(row, previous_status):
	"""Verified/Rejected need the verifier role; a changed status records who and when."""
	if row.status == previous_status:
		return
	if previous_status == "Verified" and VERIFIER_ROLE not in frappe.get_roles():
		frappe.throw(_("Only an {0} can change the verified document {1}.").format(VERIFIER_ROLE, row.document_type))
	if row.status in VERIFIER_STATUSES:
		if VERIFIER_ROLE not in frappe.get_roles():
			frappe.throw(_("Only an {0} can mark {1} as {2}.").format(VERIFIER_ROLE, row.document_type, row.status))
		if row.status == "Rejected" and not row.remarks:
			frappe.throw(_("Enter remarks to reject {0}.").format(row.document_type))
		row.verified_by, row.verified_on = frappe.session.user, now_datetime()
	else:
		row.verified_by = row.verified_on = None


def set_document_status(applicant, document_type, status, remarks=None, original_retained=None):
	"""Verifier action: set the status (and optionally remarks and the originals flag) of one checklist item."""
	doc = frappe.get_doc("Student Applicant", applicant)
	doc.check_permission("write")
	row = next((r for r in doc.oc_documents if r.document_type == document_type), None)
	if not row:
		frappe.throw(_("{0} is not on the document checklist of {1}.").format(document_type, applicant))
	row.status = status
	if remarks is not None:
		row.remarks = remarks
	if original_retained is not None:
		row.original_retained = cint(original_retained)
	doc.save()
	return {"complete": documents_complete(doc), "status": row.status}


# Daily reminders
def reminder_items():
	"""[{applicant, mobile, documents}] for open applicants with an incomplete mandatory document and a mobile number."""
	names = frappe.get_all(
		"Student Applicant", {"application_status": ("in", OPEN_STATUSES), "student_mobile_number": ("is", "set")}, pluck="name", limit=0
	)
	incomplete = frappe.get_all(
		"Applicant Document",
		{"parent": ("in", names or [""]), "parenttype": "Student Applicant", "mandatory": 1, "status": ("in", ("Pending", "Rejected"))},
		["parent", "document_type", "status"],
		order_by="parent, idx",
		limit=0,
	)
	pending = {}
	for row in incomplete:
		pending.setdefault(row.parent, []).append(row.document_type)
	mobiles = dict(frappe.get_all("Student Applicant", {"name": ("in", list(pending) or [""])}, ["name", "student_mobile_number"], as_list=True))
	return [{"applicant": a, "mobile": mobiles[a], "documents": docs} for a, docs in sorted(pending.items())]


def send_daily_reminders(as_of=None):
	"""Scheduler entry point: queue one bulk run of today's reminders; returns the Bulk Run name or None."""
	day = as_of or nowdate()
	items = reminder_items()
	if items:
		return run_bulk(REMINDER_RUN_TYPE, items, REMINDER_HANDLER, key=REMINDER_KEY, parameters={"day": str(day)})


def reminder_key(item):
	return item["applicant"]


def send_reminder(item, run):
	"""Bulk handler: one reminder per applicant per day (the day is the messaging dedupe token). DB-only."""
	day = run.get_parameters()["day"]
	doc = frappe.get_doc("Student Applicant", item["applicant"])
	send(
		REMINDER_EVENT,
		doc,
		[f"phone:{item['mobile']}"],
		context={"documents": ", ".join(item["documents"]), "dedupe_token": day},
	)
