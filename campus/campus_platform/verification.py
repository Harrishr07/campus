"""M17-04, M05-04 Verifiable documents: issue / revoke / verify and the `oc_qr_block` print macro.

`issue(doc, print_format)` renders the document, stores the SHA-256 of that render and a random
10-character code in a Verifiable Document. The public page `/verify/<code>` (www/verify) looks the
code up through `verify()`.

What is hashed: the rendered print HTML, not the PDF. PDF output embeds creation/modification
timestamps (and wkhtmltopdf needs to reach the site over HTTP), so two PDF renders of the same
document never hash alike. The HTML of the same document + print format is deterministic.

Printing and issuing are separate on purpose. `oc_qr_block(doc)` (a Jinja global, registered in
hooks) only *reads* the document's latest Verifiable Document and renders nothing when there is none.
It never issues, so rendering cannot recurse into issuing. While `issue()` renders for hashing,
`frappe.flags.oc_hashing_render` makes the macro render nothing, so the hash covers the document
content only and is the same however many times (and after however many QRs) it is re-issued.
"""

import base64
import hashlib
import io
import secrets

import frappe
import pyqrcode
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import get_url, now_datetime
from markupsafe import Markup, escape

DOCTYPE = "Verifiable Document"
VERIFICATION_ROLE = "Verification Manager"
# No 0/O/1/I/L: codes get read aloud and typed from printed pages.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 10
HOLDER_NAME_FIELDS = ("student_name", "employee_name", "full_name", "applicant_name", "title")
PUBLIC_LIMIT = 30
PUBLIC_WINDOW_SECONDS = 60
MASK = "****"


def ensure_verification_role():
	if not frappe.db.exists("Role", VERIFICATION_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": VERIFICATION_ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)


# ---- issue / revoke / verify -------------------------------------------------------------


def issue(doc, print_format=None):
	"""Render `doc` with `print_format` (hashed as HTML, see module docstring); return the new record.

	Issuing the same document again creates a new record with a new code; earlier ones stay.
	"""
	rendered = render_for_hash(doc, print_format)
	record = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"code": new_code(),
			"company": _company_of(doc),
			"document_type": _(doc.doctype),
			"holder_name": holder_name(doc),
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"print_format": print_format,
			"sha256": hashlib.sha256(rendered.encode()).hexdigest(),
			"issued_on": now_datetime(),
			"issued_by": frappe.session.user,
			"status": "Valid",
		}
	)
	record.insert(ignore_permissions=True)
	return record


def render_for_hash(doc, print_format=None):
	"""Print HTML of `doc` as it is hashed: the QR block suppressed."""
	frappe.flags.oc_hashing_render = True
	try:
		return frappe.get_print(doc.doctype, doc.name, print_format)
	finally:
		frappe.flags.oc_hashing_render = False


def revoke(code_or_name, reason):
	"""Mark a Verifiable Document revoked. Needs System Manager or Verification Manager."""
	if not ({"System Manager", VERIFICATION_ROLE} & set(frappe.get_roles())):
		frappe.throw(
			_("Only a System Manager or Verification Manager can revoke documents."), frappe.PermissionError
		)
	if not (reason or "").strip():
		frappe.throw(_("A reason is required to revoke a document."))
	record = frappe.get_doc(DOCTYPE, _resolve_name(code_or_name))
	if record.status == "Revoked":
		frappe.throw(_("{0} is already revoked.").format(record.name))
	record.status = "Revoked"
	record.revoked_on = now_datetime()
	record.revoked_by = frappe.session.user
	record.revocation_reason = reason.strip()
	record.save(ignore_permissions=True)
	return record


def revoke_for(doc, reason):
	"""Revoke every valid Verifiable Document issued for `doc`, e.g. when the document is cancelled.

	An internal path for controllers: no role check, as the caller is acting on its own document.
	"""
	for name in frappe.get_all(DOCTYPE, {"reference_doctype": doc.doctype, "reference_name": doc.name, "status": "Valid"}, pluck="name"):
		record = frappe.get_doc(DOCTYPE, name)
		record.status = "Revoked"
		record.revoked_on = now_datetime()
		record.revoked_by = frappe.session.user
		record.revocation_reason = reason
		record.save(ignore_permissions=True)


def verify(code):
	"""Pure lookup by code. Returns a dict of the verifiable facts, or None for an unknown code."""
	name = frappe.db.get_value(DOCTYPE, {"code": normalize_code(code)}, "name")
	if not name:
		return None
	return frappe.db.get_value(
		DOCTYPE,
		name,
		[
			"code",
			"company",
			"document_type",
			"holder_name",
			"issued_on",
			"status",
			"revoked_on",
			"revocation_reason",
		],
		as_dict=True,
	)


def normalize_code(code):
	return (code or "").strip().upper()


def new_code():
	while True:
		code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
		if not frappe.db.exists(DOCTYPE, {"code": code}):
			return code


def _resolve_name(code_or_name):
	name = frappe.db.get_value(DOCTYPE, {"code": normalize_code(code_or_name)}, "name")
	if not name:
		frappe.throw(_("Verifiable Document {0} not found.").format(code_or_name), frappe.DoesNotExistError)
	return name


# ---- holder and issuer -------------------------------------------------------------------


def holder_name(doc):
	"""Person the document is about: first filled name-like field, else the document name."""
	for field in HOLDER_NAME_FIELDS:
		value = doc.get(field)
		if value and str(value).strip():
			return str(value).strip()
	return doc.name


def mask_name(name):
	"""'Rahul Kumar' -> 'R**** K****'. Fixed-width stars so the length of a name is not leaked."""
	return " ".join(word[0] + MASK for word in (name or "").split())


def _company_of(doc):
	return doc.get("company") or doc.get("oc_company")


# ---- public lookup (rate limited) -------------------------------------------------------


@rate_limit(limit=PUBLIC_LIMIT, seconds=PUBLIC_WINDOW_SECONDS)
def public_lookup(code):
	"""Throttled per IP (30/min): raises RateLimitExceededError (HTTP 429) beyond that.

	Returns the page data with the holder name masked; None for an unknown code.
	"""
	found = verify(code)
	if found:
		found["holder_name"] = mask_name(found.holder_name)
	return found


@frappe.whitelist(allow_guest=True)
def verify_public(code):
	"""Guest-callable JSON twin of the public page."""
	return public_lookup(code)


# ---- QR ----------------------------------------------------------------------------------


def verification_url(code):
	base = frappe.db.get_single_value("Campus Settings", "verification_base_url") or get_url()
	return f"{base.rstrip('/')}/verify/{code}"


def qr_data_uri(text):
	buffer = io.BytesIO()
	pyqrcode.create(text, error="M").png(buffer, scale=4, quiet_zone=2)
	return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def oc_qr_block(doc):
	"""Jinja global for print formats: `{{ oc_qr_block(doc) }}`.

	Shows the QR, code and URL of the document's latest Verifiable Document, nothing if never
	issued. Read-only: it never issues (see module docstring).
	"""
	if frappe.flags.oc_hashing_render:
		return ""
	code = frappe.db.get_value(
		DOCTYPE,
		{"reference_doctype": doc.doctype, "reference_name": doc.name},
		"code",
		order_by="creation desc, name desc",
	)
	if not code:
		return ""
	url = verification_url(code)
	return Markup(
		'<div class="oc-qr-block" style="text-align:center;display:inline-block">'
		'<img src="{src}" alt="QR" style="width:110px;height:110px">'
		'<div style="font-family:monospace;font-size:12px;letter-spacing:1px">{code}</div>'
		'<div style="font-size:9px">{label}: {url}</div></div>'
	).format(src=qr_data_uri(url), code=escape(code), label=escape(_("Verify at")), url=escape(url))
