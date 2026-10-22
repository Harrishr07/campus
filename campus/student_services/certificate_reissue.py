"""M05-14 Certificate correction, supersession and reissue.

A Certificate Request with `supersedes` set replaces an issued one (a correction of particulars, or a duplicate for a
damaged or lost certificate). It always goes through approval (the seeded "Certificate Reissue" policy, or the
college's own), gets a new serial number and, if the type has a Duplicate Fee, raises it once through the existing
certificate fee path (a correction is free). On issue the original is marked Superseded and its Verifiable Document
shows the current certificate; nothing is deleted. Cancelling the reissue puts the original back; cancelling a
superseded original is refused.

Transfer certificate: the Withdrawn transition belongs to the original TC and is never run again. A reissued TC only
repoints the Student's leaving fields at the new certificate; cancelling it restores them to the original.

A duplicate (not a correction) of an examination certificate keeps the original's frozen record snapshot.
"""

import frappe
from frappe import _
from markupsafe import Markup, escape

from campus.campus_platform import verification

REQUEST = "Certificate Request"
CORRECTION, DAMAGED, LOST, DUPLICATE = "Correction of Particulars", "Damaged", "Lost", "Duplicate"
EVIDENCE_REASONS = (CORRECTION, LOST)
REISSUED_MARK, DUPLICATE_MARK = "Reissued", "Duplicate"
POLICY = "Certificate Reissue"
POLICY_PRIORITY = 10


def marking_for(reason):
	return REISSUED_MARK if reason == CORRECTION else DUPLICATE_MARK


def keeps_original_record(doc):
	"""True for a duplicate: it must print what the original printed, not the record as it stands now."""
	return bool(doc.get("supersedes")) and doc.reissue_reason != CORRECTION


# ---- request side ----------------------------------------------------------------------------


def apply_terms(doc, kind):
	"""Draft: a reissue always needs approval; its fee, marking and (for a TC) leaving fields follow the reason."""
	original = frappe.db.get_value(REQUEST, doc.supersedes, ["leaving_date", "reason_for_leaving"], as_dict=True)
	doc.needs_approval = 1
	doc.fee_amount = 0 if doc.reissue_reason == CORRECTION else kind.reissue_fee
	doc.marking = marking_for(doc.reissue_reason) if kind.mark_reissues else None
	if kind.is_transfer_certificate and doc.reissue_reason != CORRECTION:
		doc.leaving_date, doc.reason_for_leaving = original.leaving_date, original.reason_for_leaving
	elif kind.is_transfer_certificate:
		doc.leaving_date = doc.leaving_date or original.leaving_date


def validate_reissue(doc):
	"""Draft: the original is an issued, current certificate of this student and type; the evidence is private."""
	if not doc.supersedes:
		return
	original = frappe.db.get_value(
		REQUEST, doc.supersedes, ["docstatus", "student", "certificate_type", "superseded_by"], as_dict=True
	)
	if not original or original.docstatus != 1:
		frappe.throw(_("{0} is not an issued certificate, so it cannot be superseded.").format(frappe.bold(doc.supersedes)))
	if (original.student, original.certificate_type) != (doc.student, doc.certificate_type):
		frappe.throw(_("A reissue is for the same student and certificate type as {0}.").format(frappe.bold(doc.supersedes)))
	if original.superseded_by:
		frappe.throw(_("{0} was already superseded by {1}.").format(frappe.bold(doc.supersedes), original.superseded_by))
	if doc.reissue_reason in EVIDENCE_REASONS and not doc.evidence:
		frappe.throw(_("Attach the evidence for a {0} reissue.").format(_(doc.reissue_reason)))
	if doc.reissue_reason == LOST and not (doc.reference_note or "").strip():
		frappe.throw(_("Give the affidavit or FIR reference for a lost certificate."))
	if doc.evidence and not doc.evidence.startswith("/private/"):
		frappe.throw(_("The evidence must be a private file."))


def lock_original(doc):
	"""Submit: re-check, under a lock, that the original is still issued and current."""
	original = frappe.db.get_value(REQUEST, doc.supersedes, ["docstatus", "superseded_by"], as_dict=True, for_update=True)
	if original.docstatus != 1 or original.superseded_by:
		frappe.throw(_("{0} is no longer a current certificate and cannot be superseded.").format(frappe.bold(doc.supersedes)))


def supersede(doc):
	"""Issue: the original becomes Superseded, its QR points to this certificate; a TC repoints the Student."""
	original = frappe.db.get_value(REQUEST, doc.supersedes, ["name", "docstatus", "superseded_by"], as_dict=True, for_update=True)
	frappe.db.set_value(REQUEST, original.name, "superseded_by", doc.name, update_modified=False)
	verification.supersede_for(frappe._dict(doctype=REQUEST, name=original.name), frappe._dict(doctype=REQUEST, name=doc.name))
	if doc.is_transfer_certificate:
		frappe.db.set_value(
			"Student", doc.student,
			{"leaving_certificate_number": doc.certificate_number, "date_of_leaving": doc.leaving_date, "reason_for_leaving": doc.reason_for_leaving},
		)  # fmt: skip


def reinstate(doc):
	"""Cancel of a reissue: the original is current again (and, for a TC, the Student points at it)."""
	original = frappe.db.get_value(
		REQUEST, doc.supersedes, ["name", "superseded_by", "certificate_number", "leaving_date", "reason_for_leaving"],
		as_dict=True, for_update=True,
	)  # fmt: skip
	if original.superseded_by != doc.name:
		return
	frappe.db.set_value(REQUEST, original.name, "superseded_by", None, update_modified=False)
	verification.reinstate_for(frappe._dict(doctype=REQUEST, name=original.name))
	if doc.is_transfer_certificate and frappe.db.get_value("Student", doc.student, "leaving_certificate_number") == doc.certificate_number:
		frappe.db.set_value(
			"Student", doc.student,
			{"leaving_certificate_number": original.certificate_number, "date_of_leaving": original.leaving_date, "reason_for_leaving": original.reason_for_leaving},
		)  # fmt: skip


def refuse_cancel_of_superseded(doc):
	replacement = frappe.db.get_value(REQUEST, doc.name, "superseded_by", for_update=True)
	if replacement and frappe.db.get_value(REQUEST, replacement, "docstatus") == 1:
		frappe.throw(_("{0} was superseded by {1}. Cancel {1} first.").format(doc.name, replacement))


# ---- print -----------------------------------------------------------------------------------


def oc_reissue_mark(doc):
	"""Jinja global for the certificate print formats: DUPLICATE / REISSUED banner of a reissued certificate."""
	if not doc.get("marking"):
		return ""
	original = frappe.db.get_value(REQUEST, doc.supersedes, "certificate_number") if doc.get("supersedes") else None
	note = _("In place of No. {0}").format(escape(original)) if original else ""
	return Markup(
		'<div class="oc-reissue-mark" style="text-align:center;font-weight:bold;letter-spacing:4px;border:2px solid #000;padding:2px">'
		"{label}</div><div style=\"text-align:center;font-size:11px\">{note}</div>"
	).format(label=escape(_(doc.marking).upper()), note=Markup(note))


# ---- seed ------------------------------------------------------------------------------------


def seed_reissue_policy():
	"""The Principal of the student's college approves every reissue, unless the college has its own policy for it."""
	if frappe.db.exists("Approval Policy", POLICY) or not frappe.db.exists("Position", "PRINCIPAL"):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": POLICY, "document_type": REQUEST, "condition": "doc.supersedes",
			"priority": POLICY_PRIORITY,
			"levels": [{"approver_type": "Position", "approver": "PRINCIPAL", "scope_field": "company", "title": "Principal", "sla_hours": 72}],
		}
	).insert(ignore_permissions=True)  # fmt: skip
